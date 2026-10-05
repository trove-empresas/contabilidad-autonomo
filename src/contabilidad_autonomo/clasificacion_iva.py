"""Clasificación de IVA con reglas que citan su norma (v1, issue #11).

Código puro y determinista: la IA solo aporta los datos extraídos; aquí se
decide la clasificación. Si los datos no bastan o son incoherentes, el
resultado es **indeterminado** (``clasificacion=None`` con un motivo) y la
factura debe quedar pendiente de confirmación del usuario; nunca se adivina.

Clasificaciones (los tres nombres especiales son los que ya usa
``pendientes``):

* ``general`` / ``reducido`` / ``superreducido``: sujeta y no exenta.
* ``exenta``, ``no_sujeta``, ``isp`` (inversión del sujeto pasivo).

Cada regla (``REGLAS``) lleva norma, artículo y fecha desde la que aplica
(principio 4 de CLAUDE.md); ``Regla`` rechaza una sin referencia. Una regla
solo se usa si la fecha de la factura cae en su vigencia.

AVISO — las referencias normativas están escritas de memoria y **no se han
contrastado con el BOE**; los apartados concretos y las fechas deben ser
revisados por Gonzalo (o un asesor) antes de dar por buena esta clasificación.

Límites conocidos:

* Se usa la fecha de la factura como fecha de devengo.
* Solo IVA peninsular y Baleares; Canarias, Ceuta y Melilla (IGIC/IPSI) no
  están cubiertos y los tipos distintos de 21, 10 y 4 % quedan indeterminados
  (incluidos tipos temporales o recargo de equivalencia).
* El tipo reducido/superreducido se clasifica por el tipo aplicado en la
  factura; no se comprueba que el concepto realmente le corresponda.
* Exenta y no sujeta (salvo servicios emitidos a empresa extranjera) las
  declara quien aporta los datos; aquí solo se comprueba la coherencia (sin
  IVA repercutido) y, para la exenta, que cite el apartado del art. 20.
* La inversión del sujeto pasivo solo cubre **servicios** recibidos de un
  proveedor no español. Entregas de bienes, adquisiciones intracomunitarias e
  importaciones quedan indeterminadas.
* Nada de esto presenta modelos: solo clasifica.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ESPECIALES = frozenset({"exenta", "no_sujeta", "isp"})
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
           "Tipo general del 21 %. Desde 2012-09-01 (RDL 20/2012)."),
    _regla("tipo_reducido", "art. 91.Uno", date(2012, 9, 1),
           "Tipo reducido del 10 %. Desde 2012-09-01 (RDL 20/2012)."),
    _regla("tipo_superreducido", "art. 91.Dos", date(1995, 1, 1),
           "Tipo superreducido del 4 %."),
    _regla("exencion", "art. 20", date(1993, 1, 1),
           "Operaciones exentas; el apartado concreto lo cita la factura."),
    _regla("no_sujecion", "art. 7", date(1993, 1, 1),
           "Operaciones no sujetas."),
    _regla("localizacion_servicios", "art. 69.Uno.1º", date(2010, 1, 1),
           "Servicio a empresario o profesional: se grava donde está establecido "
           "el destinatario; a un destinatario extranjero, no sujeto en España."),
    _regla("isp_servicios", "art. 84.Uno.2º y art. 69.Uno.1º", date(2010, 1, 1),
           "Servicio recibido de proveedor no establecido en España: el sujeto "
           "pasivo es el destinatario (inversión del sujeto pasivo)."),
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


def pais_de(nif: str, pais: str | None = None) -> str | None:
    """País de la contraparte: el explícito, o ``ES`` / prefijo del NIF; si no, None."""
    if pais and pais.strip():
        return pais.strip().upper()
    n = nif.strip().upper().replace("-", "").replace(" ", "")
    if re.fullmatch(r"(ES)?[0-9A-Z][0-9]{7}[0-9A-Z]", n):
        return "ES"
    m = re.fullmatch(r"([A-Z]{2})[0-9A-Z]{2,12}", n)
    return m.group(1) if m else None


def _ok(clasificacion: str, regla_id: str, fecha: date, motivo: str) -> Resultado:
    regla = REGLAS[regla_id]
    if not regla.vigente(fecha):
        return _dudoso(f"la regla {regla.articulo} no estaba vigente el {fecha}")
    return Resultado(clasificacion, regla, motivo)


def _dudoso(motivo: str) -> Resultado:
    return Resultado(None, None, motivo)


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
            return _dudoso("contraparte extranjera con IVA español repercutido")
        if op.tipo == "recibida":
            return _ok("isp", "isp_servicios", op.fecha,
                       f"servicio de proveedor no establecido en España ({pais})")
        return _ok("no_sujeta", "localizacion_servicios", op.fecha,
                   f"servicio a destinatario establecido fuera de España ({pais})")

    if pais is None and sin_iva:
        return _dudoso("sin IVA y no se identifica el país de la contraparte")

    clave = _TIPO_A_REGLA.get(op.tipo_iva)
    if clave is None:
        return _dudoso(f"tipo de IVA {op.tipo_iva} % no reconocido para operación sujeta")
    return _ok(clave[0], clave[1], op.fecha, f"tipo {op.tipo_iva} %")
