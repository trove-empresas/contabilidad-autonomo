"""Reglas deterministas que dejan una factura pendiente (v1, issue #10).

Implementa la decisión «Umbral de confianza inicial: 0,90» de
docs/decisiones.md. Todo es código puro: la IA solo aporta los datos y su
confianza; aquí se decide, sin IA, si la factura puede entrar en los cálculos
o debe confirmarla el usuario.

Una factura queda pendiente, con un motivo por cada regla que se incumple, si:

* su confianza (la más baja de extracción y clasificación) es menor que el
  umbral (``UMBRAL_CONFIANZA``, por defecto 0,90);
* los importes no cuadran (bases + cuotas − retención ≠ total, con margen de
  1 céntimo por cada tipo de IVA distinto);
* algún NIF no supera su dígito o letra de control;
* falta algún campo clave;
* la clasificación es exenta, no sujeta o inversión del sujeto pasivo y es la
  primera vez que aparece esa contraparte con esa clasificación.

Una factura ya confirmada por el usuario no se vuelve a evaluar: su
confirmación manda. El filtro de cálculo es ``para_calculo``.

Límites conocidos (se anotan para que no sorprendan):

* NIF españoles: DNI, NIE y CIF. Un identificador que empieza por dos letras
  distintas de ``ES`` se toma como número de IVA extranjero y no se verifica
  (no hay una regla común). Cualquier otro formato se da por NIF inválido
  y la factura queda pendiente (se prefiere confirmar de más).
* Los NIF que empiezan por K, L o M se aceptan si cuadran con cualquiera de
  las dos formas de control del CIF (dígito o letra).
* Los nombres de clasificación especial son provisionales hasta que la
  issue #11 fije los definitivos.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from contabilidad_autonomo.facturas import (
    CONFIRMADA,
    EMITIDA,
    Factura,
    a_centimos,
)

UMBRAL_POR_DEFECTO = Decimal("0.90")

# Provisional: la issue #11 definirá los nombres definitivos de clasificación.
CLASIFICACIONES_ESPECIALES = frozenset({"exenta", "no_sujeta", "isp"})

_LETRAS_DNI = "TRWAGMYFPDXBNJZSQVHLCKE"
_LETRAS_CIF = "JABCDEFGHI"
_CIF_SOLO_LETRA = "PQRSNW"
_CIF_SOLO_DIGITO = "ABEH"


def umbral_confianza(entorno: dict[str, str] | None = None) -> Decimal:
    """Lee ``UMBRAL_CONFIANZA`` (entre 0 y 1); si falta, 0,90.

    Un valor ilegible o fuera de rango es un error, no se ignora: un umbral
    mal escrito no debe relajar la comprobación sin avisar.
    """
    entorno = os.environ if entorno is None else entorno
    bruto = entorno.get("UMBRAL_CONFIANZA", "").strip()
    if not bruto:
        return UMBRAL_POR_DEFECTO
    try:
        valor = Decimal(bruto)
    except InvalidOperation:
        raise ValueError(f"UMBRAL_CONFIANZA no es un número: {bruto!r}") from None
    if not valor.is_finite() or not (Decimal(0) <= valor <= Decimal(1)):
        raise ValueError(f"UMBRAL_CONFIANZA debe estar entre 0 y 1: {bruto!r}")
    return valor


def nif_valido(nif: str) -> bool:
    """Comprueba letra/dígito de control de DNI, NIE y CIF españoles."""
    n = nif.strip().upper().replace("-", "").replace(" ", "")
    if re.fullmatch(r"ES[0-9A-Z]{9}", n):
        n = n[2:]
    elif not n.startswith("ES") and re.fullmatch(r"[A-Z]{2}[0-9A-Z]{2,12}", n):
        return True  # número de IVA extranjero: no verificable (ver cabecera)
    if re.fullmatch(r"[0-9]{8}[A-Z]", n):
        return _LETRAS_DNI[int(n[:8]) % 23] == n[8]
    if re.fullmatch(r"[XYZ][0-9]{7}[A-Z]", n):
        cuerpo = str("XYZ".index(n[0])) + n[1:8]
        return _LETRAS_DNI[int(cuerpo) % 23] == n[8]
    if re.fullmatch(r"[A-HJNPQRSUVWKLM][0-9]{7}[0-9A-J]", n):
        digitos = n[1:8]
        suma = sum(int(d) for d in digitos[1::2])
        for d in digitos[0::2]:
            doble = int(d) * 2
            suma += doble // 10 + doble % 10
        control = (10 - suma % 10) % 10
        esperado_digito, esperado_letra = str(control), _LETRAS_CIF[control]
        if n[0] in _CIF_SOLO_LETRA:
            return n[8] == esperado_letra
        if n[0] in _CIF_SOLO_DIGITO:
            return n[8] == esperado_digito
        return n[8] in (esperado_digito, esperado_letra)
    return False


def _contraparte_nif(f: Factura) -> str:
    return (f.receptor_nif if f.tipo == EMITIDA else f.emisor_nif).strip().upper()


def _campos_ausentes(f: Factura) -> list[str]:
    ausentes = []
    for nombre, valor in (
        ("NIF del emisor", f.emisor_nif),
        ("NIF del receptor", f.receptor_nif),
        ("número", f.numero),
    ):
        if not valor.strip():
            ausentes.append(nombre)
    if not f.lineas:
        ausentes.append("desglose de IVA")
    if f.clasificacion_iva is None or not f.clasificacion_iva.strip():
        ausentes.append("clasificación de IVA")
    return ausentes


def _no_cuadra(f: Factura) -> str | None:
    if not f.lineas:
        return None  # ya consta como campo ausente
    bases = sum(a_centimos(l.base) for l in f.lineas)
    cuotas = sum(a_centimos(l.cuota) for l in f.lineas)
    esperado = bases + cuotas - a_centimos(f.retencion_irpf)
    tipos = len({l.tipo_iva for l in f.lineas})
    diferencia = abs(esperado - a_centimos(f.total))
    if diferencia > tipos:  # 1 céntimo por tipo de IVA
        return (f"los importes no cuadran: bases + cuotas − retención "
                f"= {esperado / 100:.2f} y el total es {f.total}")
    return None


def motivos_pendiente(
    f: Factura,
    conocidas: Iterable[tuple[str, str]] = (),
    umbral: Decimal | None = None,
) -> list[str]:
    """Motivos por los que ``f`` debe quedar pendiente (vacío = puede entrar).

    ``conocidas`` son pares ``(NIF de la contraparte, clasificación)`` que el
    usuario ya confirmó antes (ver ``clasificaciones_conocidas``).
    """
    umbral = UMBRAL_POR_DEFECTO if umbral is None else umbral
    motivos: list[str] = []

    confianzas = [f.confianza_extraccion]
    if f.confianza_clasificacion is not None:
        confianzas.append(f.confianza_clasificacion)
    minima = min(confianzas)
    if minima < umbral:
        motivos.append(f"confianza {minima} menor que el umbral {umbral}")

    cuadre = _no_cuadra(f)
    if cuadre:
        motivos.append(cuadre)

    for etiqueta, nif in (("emisor", f.emisor_nif), ("receptor", f.receptor_nif)):
        if nif.strip() and not nif_valido(nif):
            motivos.append(f"NIF del {etiqueta} no supera la comprobación de control")

    ausentes = _campos_ausentes(f)
    if ausentes:
        motivos.append("falta: " + ", ".join(ausentes))

    clas = (f.clasificacion_iva or "").strip()
    if clas in CLASIFICACIONES_ESPECIALES:
        if (_contraparte_nif(f), clas) not in set(conocidas):
            motivos.append(f"primera vez que esta contraparte aparece como «{clas}»")
    return motivos


def esta_pendiente(f: Factura, conocidas: Iterable[tuple[str, str]] = (),
                   umbral: Decimal | None = None) -> bool:
    return bool(motivos_pendiente(f, conocidas, umbral))


def clasificaciones_conocidas(con: sqlite3.Connection) -> set[tuple[str, str]]:
    """Pares (NIF de la contraparte, clasificación) ya confirmados."""
    conocidas = set()
    filas = con.execute(
        "SELECT tipo, emisor_nif, receptor_nif, clasificacion_iva FROM facturas"
        " WHERE estado = ? AND clasificacion_iva IS NOT NULL", (CONFIRMADA,))
    for tipo, emisor, receptor, clas in filas:
        nif = receptor if tipo == EMITIDA else emisor
        conocidas.add((nif.strip().upper(), clas.strip()))
    return conocidas


def para_calculo(facturas: Iterable[Factura]) -> list[Factura]:
    """Filtro único para todos los cálculos: solo facturas confirmadas.

    Ningún cálculo (303, 130…) debe leer facturas sin pasar por aquí.
    """
    return [f for f in facturas if f.estado == CONFIRMADA]
