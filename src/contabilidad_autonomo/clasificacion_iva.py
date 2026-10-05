"""Clasificación de IVA con reglas que citan su norma (v1, issue #11).

Código puro y determinista: la IA solo aporta los datos extraídos; aquí se
decide la clasificación. Si los datos no bastan o son incoherentes, el
resultado es **indeterminado** (``clasificacion=None`` con un motivo) y la
factura debe quedar pendiente de confirmación del usuario; nunca se adivina.

Clasificaciones (los tres nombres especiales son los que ya usa
``pendientes``):

* ``general`` / ``reducido`` / ``superreducido``: sujeta y no exenta.
* ``exenta``, ``no_sujeta`` (art. 7), ``isp`` (inversión del sujeto pasivo).
* ``no_sujeta_loc_ue`` / ``no_sujeta_loc_no_ue``: servicio a empresario o
  profesional establecido fuera de España, no sujeto por las reglas de
  localización. Se separan de ``no_sujeta`` y entre sí porque van a casillas
  distintas del 303 y las de la UE, además, al modelo 349.

Cada regla (``REGLAS``) lleva norma, artículo y fecha desde la que aplica
(principio 4 de CLAUDE.md); ``Regla`` rechaza una sin referencia. Una regla
solo se usa si la fecha de la factura cae en su vigencia.

Contraste con el BOE: ver ``FECHA_CONTRASTE`` y la nota de cada regla. Lo
contrastado es el texto consolidado de la Ley 37/1992 en www.boe.es (artículos
7, 20, 69, 84, 90 y 91). Lo que NO se ha podido contrastar queda marcado como
«sin contrastar» en la regla correspondiente.

Límites conocidos:

* Se usa la fecha de la factura como fecha de devengo.
* Solo IVA peninsular y Baleares; Canarias, Ceuta y Melilla (IGIC/IPSI) no
  están cubiertos y los tipos distintos de 21, 10 y 4 % quedan indeterminados
  (incluidos tipos temporales o recargo de equivalencia).
* El tipo reducido/superreducido se clasifica por el tipo aplicado en la
  factura; no se comprueba que el concepto realmente le corresponda.
* Exenta y no sujeta (art. 7; los servicios a empresa extranjera se deducen
  de los datos) las declara quien aporta los datos; aquí solo se comprueba la coherencia (sin
  IVA repercutido) y, para la exenta, que cite el apartado del art. 20.
* La inversión del sujeto pasivo solo cubre **servicios** recibidos de un
  proveedor no español. Entregas de bienes, adquisiciones intracomunitarias e
  importaciones quedan indeterminadas.
* Las reglas especiales de localización (art. 70: inmuebles, transporte,
  etc.) no están cubiertas: un servicio con regla especial puede salir mal
  clasificado. Los países de la UE son los 27 actuales (sin contrastar con
  el Tratado) y un país sin IVA español (Canarias, Ceuta, Melilla) no se
  distingue de ``ES``.
* El Real Decreto-ley 26/2026 modifica desde 2026-12-01 apartados de los
  tipos reducido y superreducido (art. 91): no cambia los tipos 10 y 4 %, pero
  sí qué conceptos entran en cada uno (el código no mira el concepto).
* Nada de esto presenta modelos: solo clasifica.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

FECHA_CONTRASTE = date(2026, 10, 5)  # consulta de www.boe.es (ver cabecera)
ESPECIALES = frozenset(
    {"exenta", "no_sujeta", "isp", "no_sujeta_loc_ue", "no_sujeta_loc_no_ue"})
# Estados miembros de la UE (ISO-2). Sin contrastar con el Tratado; ver cabecera.
PAISES_UE = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI SE".split())
_TIPOS_OPERACION = ("sujeta", "exenta", "no_sujeta")
_LIVA = "Ley 37/1992 del IVA"


@dataclass(frozen=True)
class Regla:
    id: str
    norma: str
    articulo: str
    desde: date
    hasta: date | None
    descripcion: str

    def __post_init__(self) -> None:
        if not self.norma.strip() or not self.articulo.strip():
            raise ValueError(f"La regla {self.id!r} no tiene referencia normativa.")

    def vigente(self, fecha: date) -> bool:
        return self.desde <= fecha and (self.hasta is None or fecha <= self.hasta)


def _regla(id_: str, articulo: str, desde: date, descripcion: str, norma: str = _LIVA) -> Regla:
    return Regla(id_, norma, articulo, desde, None, descripcion)


REGLAS: dict[str, Regla] = {r.id: r for r in (
    _regla("tipo_general", "art. 90.Uno", date(2012, 9, 1),
           "Tipo general del 21 %. Desde 2012-09-01 (RDL 20/2012). "
           "Contrastado en BOE 2026-10-05."),
    _regla("tipo_reducido", "art. 91.Uno", date(2012, 9, 1),
           "Tipo reducido del 10 %. Desde 2012-09-01 (RDL 20/2012). "
           "Contrastado en BOE 2026-10-05."),
    _regla("tipo_superreducido", "art. 91.Dos", date(1995, 1, 1),
           "Tipo superreducido del 4 %. Desde 1995-01-01 (Ley 41/1994). "
           "Contrastado en BOE 2026-10-05."),
    _regla("exencion", "art. 20", date(1993, 1, 1),
           "Operaciones exentas; el apartado concreto lo cita la factura. "
           "Artículo contrastado en BOE 2026-10-05; el apartado no."),
    _regla("no_sujecion", "art. 7", date(1993, 1, 1),
           "Operaciones no sujetas (supuestos del art. 7, no los de localización). "
           "Contrastado en BOE 2026-10-05."),
    _regla("localizacion_servicios", "art. 69.Uno.1º (a sensu contrario)",
           date(2010, 1, 1),
           "Servicio a empresario o profesional (art. 5): se localiza donde está "
           "establecido el destinatario; si es fuera de España, no sujeto en España. "
           "El texto del art. 69.Uno.1º solo dice cuándo SÍ está sujeto; la no "
           "sujeción es la lectura contraria. Redacción vigente desde 2010-01-01 "
           "(Ley 2/2010), contrastada en BOE 2026-10-05. No contrastada la "
           "correspondencia con las casillas del 303 ni con el modelo 349."),
    _regla("isp_servicios", "art. 84.Uno.2º.a)", date(2010, 1, 1),
           "Servicio recibido de proveedor no establecido en España: el sujeto "
           "pasivo es el destinatario (inversión del sujeto pasivo), salvo las "
           "excepciones de la letra a'). Contrastado en BOE 2026-10-05; la fecha "
           "2010-01-01 sigue la del art. 69 (no contrastada para el 84)."),
)}

_TIPO_A_REGLA = {Decimal(21): ("general", "tipo_general"),
                 Decimal(10): ("reducido", "tipo_reducido"),
                 Decimal(4): ("superreducido", "tipo_superreducido")}


@dataclass(frozen=True)
class Operacion:
    tipo: str  # "emitida" | "recibida"
    fecha: date
    tipo_iva: Decimal | None  # porcentaje aplicado; None si no consta
    nif_contraparte: str
    es_servicio: bool = True
    operacion: str = "sujeta"  # "sujeta" | "exenta" | "no_sujeta" (declarada)
    articulo_exencion: str = ""  # apartado del art. 20, si operacion == "exenta"
    pais_contraparte: str | None = None  # ISO-2; si falta, se deduce del NIF
    # Solo para servicios con contraparte extranjera: ¿consta que es empresario
    # o profesional actuando como tal? None = no consta.
    contraparte_empresario: bool | None = None
    # País del IVA que figura en la factura (ISO-2) cuando tipo_iva != 0;
    # None = no consta.
    iva_pais: str | None = None

    def __post_init__(self) -> None:
        if self.tipo not in ("emitida", "recibida"):
            raise ValueError(f"Tipo de factura desconocido: {self.tipo!r}")
        if self.operacion not in _TIPOS_OPERACION:
            raise ValueError(f"Tipo de operación desconocido: {self.operacion!r}")


@dataclass(frozen=True)
class Resultado:
    clasificacion: str | None
    regla: Regla | None
    motivo: str


def _es_nif_espanol(n: str) -> bool:
    if not re.fullmatch(r"[0-9XYZA-HJNPQRSUVWKLM][0-9]{7}[0-9A-Z]", n):
        return False
    # Import local: pendientes importa este módulo (ESPECIALES).
    from contabilidad_autonomo.pendientes import nif_valido
    return nif_valido(n)


def pais_de(nif: str, pais: str | None = None) -> str | None:
    """País de la contraparte, o None si no se sabe.

    El explícito manda. Si no, ``ES`` solo si es un NIF, NIE o CIF español con
    dígito de control válido (con o sin prefijo ``ES``); un número de IVA
    extranjero da su prefijo (``EL`` se toma como ``GR``). Cualquier otra cosa
    (por ejemplo un EIN de EE. UU. de 9 dígitos) es país desconocido.
    """
    if pais and pais.strip():
        return pais.strip().upper()
    n = nif.strip().upper().replace("-", "").replace(" ", "")
    m = re.fullmatch(r"([A-Z]{2})([0-9A-Z]{2,12})", n)
    if m and m.group(1) != "ES":
        return "GR" if m.group(1) == "EL" else m.group(1)
    if n.startswith("ES"):
        n = n[2:]
    return "ES" if _es_nif_espanol(n) else None


def _ok(clasificacion: str, regla_id: str, fecha: date, motivo: str) -> Resultado:
    regla = REGLAS[regla_id]
    if not regla.vigente(fecha):
        return _dudoso(f"la regla {regla.articulo} no estaba vigente el {fecha}")
    return Resultado(clasificacion, regla, motivo)


def _dudoso(motivo: str) -> Resultado:
    return Resultado(None, None, motivo)


def _motivo_iva_extranjero(op: Operacion, pais: str) -> str:
    if op.tipo == "emitida":
        return (f"servicio emitido a contraparte extranjera ({pais}) con IVA "
                "repercutido: hay que confirmar si el destinatario es empresario "
                "o profesional (entonces no debería llevar IVA español)")
    iva = (op.iva_pais or "").strip().upper()
    if not iva:
        return (f"proveedor extranjero ({pais}) con IVA y no consta de qué país: "
                "puede ser IVA extranjero (no deducible en el 303) o IVA español "
                "cobrado por el proveedor; hay que confirmarlo")
    if iva == "ES":
        return (f"IVA español cobrado por proveedor extranjero ({pais}), p. ej. "
                "servicios digitales a particular: hay que confirmar cómo se declara")
    return (f"IVA extranjero ({iva}) soportado en el extranjero (p. ej. hostelería): "
            "no deducible en el 303; hay que confirmarlo")


def clasificar(op: Operacion) -> Resultado:
    pais = pais_de(op.nif_contraparte, op.pais_contraparte)
    extranjera = pais is not None and pais != "ES"
    sin_iva = op.tipo_iva is not None and op.tipo_iva == 0

    if op.operacion == "exenta":
        if not op.articulo_exencion.strip():
            return _dudoso("exenta sin indicar el apartado del art. 20 de la Ley del IVA")
        if not sin_iva:
            return _dudoso("operación exenta con IVA repercutido o sin tipo")
        return _ok("exenta", "exencion", op.fecha, f"art. 20 apartado {op.articulo_exencion}")

    if op.operacion == "no_sujeta":
        if not sin_iva:
            return _dudoso("operación no sujeta con IVA repercutido o sin tipo")
        return _ok("no_sujeta", "no_sujecion", op.fecha, "declarada no sujeta (art. 7)")

    if op.tipo_iva is None:
        return _dudoso("no consta el tipo de IVA")

    if extranjera:
        if not op.es_servicio:
            return _dudoso("entrega de bienes con contraparte extranjera: no clasificable")
        if not sin_iva:
            return _dudoso(_motivo_iva_extranjero(op, pais))
        if op.tipo == "recibida":
            return _ok("isp", "isp_servicios", op.fecha,
                       f"servicio de proveedor no establecido en España ({pais})")
        if op.contraparte_empresario is not True:
            return _dudoso(f"servicio emitido a contraparte extranjera ({pais}): "
                           "no consta que sea empresario o profesional")
        en_ue = pais in PAISES_UE
        return _ok("no_sujeta_loc_ue" if en_ue else "no_sujeta_loc_no_ue",
                   "localizacion_servicios", op.fecha,
                   f"servicio a empresario establecido fuera de España ({pais}, "
                   + ("UE; además va al modelo 349)" if en_ue else "fuera de la UE)"))

    if pais is None:
        if sin_iva:
            return _dudoso("sin IVA y no se identifica el país de la contraparte")
        if op.nif_contraparte.strip():
            return _dudoso("identificador de la contraparte no reconocido: "
                           "no se puede saber si es español")

    clave = _TIPO_A_REGLA.get(op.tipo_iva)
    if clave is None:
        return _dudoso(f"tipo de IVA {op.tipo_iva} % no reconocido para operación sujeta")
    return _ok(clave[0], clave[1], op.fecha, f"tipo {op.tipo_iva} %")
