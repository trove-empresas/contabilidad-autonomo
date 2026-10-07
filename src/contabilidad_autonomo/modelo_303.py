"""Cálculo del modelo 303 trimestral (v1, issue #12).

Código puro y determinista (principio 1 de CLAUDE.md): recibe facturas y
devuelve importes con ``Decimal``. No presenta nada ni asigna casillas del
formulario (la correspondencia con las casillas no se ha contrastado).

Qué entra en el cálculo:

* Solo facturas **confirmadas** (``pendientes.para_calculo``) con fecha dentro
  del trimestre. Las no confirmadas no suman: salen en ``pendientes``.
* **IVA devengado**: cuotas de las facturas emitidas por tipo (21, 10 y 4 %),
  más la cuota autorrepercutida por inversión del sujeto pasivo (ISP) en los
  servicios recibidos de proveedores no establecidos en España.
* **IVA deducible**: cuotas de las facturas recibidas que cumplen los
  requisitos, multiplicadas por el porcentaje de afectación a la actividad,
  más la cuota de la ISP, con el mismo porcentaje.
* **Resultado** = devengado − deducible. Positivo: a ingresar; negativo: a
  compensar o a devolver (aquí no se decide cuál).

Requisitos de deducción que se aplican (los indicó Gonzalo en la issue #12 y se
contrastaron con el BOE el ``FECHA_CONTRASTE``):

* Factura completa a nombre del titular con su NIF (art. 97.Uno LIVA), o
  factura simplificada con los datos del titular y la cuota desglosada (art.
  7.2 del Reglamento de facturación). Un ticket sin los datos del titular no
  permite deducir: la cuota deducible es 0 y la factura sale en
  ``no_deducidas``. En la ISP no se exige el NIF del titular porque el art.
  97.Uno.4º LIVA admite como justificante la factura o el justificante
  contable.
* El gasto debe estar afecto a la actividad (art. 95.Uno LIVA). Lo declara el
  usuario con ``DatosDeduccion.afectacion``; si no consta para una factura
  recibida, la factura queda en ``pendientes`` y **no suma** (nunca se
  adivina la afectación).
* Vehículos de turismo, remolques, ciclomotores y motocicletas, y los gastos
  directamente relacionados (art. 95.Cuatro): se presume el 50 % (art.
  95.Tres.2ª). Los supuestos del 100 % de esa regla 2.ª y las pruebas de un
  grado de utilización distinto no se modelan: el usuario puede declarar
  ``total`` o ``ninguna`` solo si es lo que le corresponde.

Límites conocidos (no se resuelven aquí):

* Fecha de la factura = fecha de devengo y de deducción (arts. 75 y 98 LIVA no
  contrastados); no se tratan facturas recibidas fuera de su trimestre.
* Prorrata, regularización de bienes de inversión, recargo de equivalencia,
  regímenes especiales, compensación de cuotas de periodos anteriores,
  adquisiciones intracomunitarias de bienes e importaciones.
* ISP: la factura no trae el tipo del IVA español, así que se asume el tipo
  general (``tipo_isp``, 21 % por defecto, art. 90.Uno LIVA). Si el servicio
  tuviera otro tipo, hay que pasarlo; el resultado lo deja anotado en
  ``supuestos``.
* El importe deducible por factura se redondea al céntimo (mitad hacia
  arriba); la norma no fija el método de redondeo (sin contrastar).
* Los importes de las líneas se suman tal cual constan; no se recalculan las
  cuotas (``pendientes`` ya comprueba que cuadran).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from contabilidad_autonomo.clasificacion_iva import REGLAS as REGLAS_CLASIFICACION
from contabilidad_autonomo.clasificacion_iva import Regla
from contabilidad_autonomo.facturas import EMITIDA, Factura
from contabilidad_autonomo.pendientes import para_calculo

FECHA_CONTRASTE = date(2026, 10, 7)  # consulta de www.boe.es (ver cabecera)

# Afectación a la actividad: nombre -> proporción deducible.
AFECTACION_TOTAL = "total"
AFECTACION_VEHICULO = "vehiculo_50"
AFECTACION_NINGUNA = "ninguna"
PROPORCION_AFECTACION = {
    AFECTACION_TOTAL: Decimal(1),
    AFECTACION_VEHICULO: Decimal("0.5"),
    AFECTACION_NINGUNA: Decimal(0),
}

_LIVA = "Ley 37/1992 del IVA"
_RFACT = "Real Decreto 1619/2012 (Reglamento de facturación)"
_TIPOS_NORMALES = ("general", "reducido", "superreducido")
_EXENTAS_O_NO_SUJETAS = ("exenta", "no_sujeta", "no_sujeta_loc_ue", "no_sujeta_loc_no_ue")


def _r(id_: str, norma: str, articulo: str, desde: date, descripcion: str) -> Regla:
    return Regla(id_, norma, articulo, desde, None, descripcion)


REGLAS: dict[str, Regla] = {r.id: r for r in (
    _r("deduccion_cuotas", _LIVA, "art. 92.Uno.1º y Dos", date(2015, 1, 1),
       "Se deducen las cuotas soportadas por repercusión directa, en la medida en que "
       "los bienes y servicios se usen en operaciones que dan derecho a deducir. "
       "Redacción vigente desde 2015-01-01 (Ley 28/2014). Contrastado en BOE 2026-10-07."),
    _r("deduccion_isp", _LIVA, "art. 92.Uno.3º", date(2015, 1, 1),
       "Se deducen también las cuotas de las prestaciones de servicios del art. "
       "84.Uno.2º (inversión del sujeto pasivo). Redacción vigente desde 2015-01-01. "
       "Contrastado en BOE 2026-10-07."),
    _r("no_deduccion_sin_intencion", _LIVA, "art. 93.Cuatro", date(2017, 11, 10),
       "No se deduce lo adquirido sin la intención de usarlo en la actividad. Se usa "
       "como respaldo de la afectación declarada. Fecha: última actualización del "
       "art. 93 (2017-11-10). Contrastado en BOE 2026-10-07."),
    _r("afectacion", _LIVA, "art. 95.Uno y Dos", date(1998, 1, 1),
       "Solo se deduce lo afecto directa y exclusivamente a la actividad. Fecha: "
       "redacción del art. 95 dada por la Ley 66/1997 (1998-01-01) para los "
       "apartados 3 y 4; los apartados 1 y 2 se contrastaron en su texto actual "
       "(BOE 2026-10-07), no versión a versión."),
    _r("vehiculos_50", _LIVA, "art. 95.Tres.2ª y Cuatro", date(1998, 1, 1),
       "Vehículos de turismo, remolques, ciclomotores y motocicletas: se presumen "
       "afectos en un 50 %. El apartado Cuatro extiende la regla a accesorios, "
       "combustibles, aparcamiento, peajes y reparaciones. Los supuestos del 100 % "
       "no se modelan. Contrastado en BOE 2026-10-07."),
    _r("requisitos_formales", _LIVA, "art. 97.Uno y Dos", date(2011, 1, 1),
       "Solo deduce quien posee el documento justificativo; si no cumple todos los "
       "requisitos, no justifica la deducción salvo rectificación. Fecha: última "
       "actualización del art. 97 (2011-01-01). Contrastado en BOE 2026-10-07."),
    _r("factura_simplificada", _RFACT, "art. 7.2", date(2013, 1, 1),
       "Para deducir con factura simplificada deben constar el NIF y el domicilio del "
       "destinatario y la cuota repercutida por separado. Texto consolidado "
       "contrastado en BOE 2026-10-07; la fecha 2013-01-01 (entrada en vigor del "
       "Reglamento) no se contrastó versión a versión."),
    _r("cuota_devengada", _LIVA, "arts. 90.Uno y 91.Uno y Dos (tipos)", date(2012, 9, 1),
       "Cuotas repercutidas por las operaciones sujetas y no exentas, por tipo. Los "
       "tipos se contrastaron (ver clasificacion_iva); el devengo (art. 75) y la "
       "repercusión (art. 88) no se contrastaron."),
)}
# Reglas de clasificacion_iva que este cálculo también aplica.
_REGLAS_EXTERNAS = ("isp_servicios", "tipo_general")


@dataclass(frozen=True)
class DatosDeduccion:
    """Lo que el usuario declara de una factura recibida para poder deducirla."""

    afectacion: str  # AFECTACION_TOTAL | AFECTACION_VEHICULO | AFECTACION_NINGUNA
    simplificada: bool = False  # ¿es una factura simplificada (ticket)?

    def __post_init__(self) -> None:
        if self.afectacion not in PROPORCION_AFECTACION:
            raise ValueError(f"Afectación desconocida: {self.afectacion!r}")


@dataclass(frozen=True)
class TotalTipo:
    tipo_iva: Decimal
    base: Decimal
    cuota: Decimal


@dataclass(frozen=True)
class Motivo:
    factura_id: int
    motivo: str


@dataclass(frozen=True)
class Resultado303:
    anio: int
    trimestre: int
    devengado_por_tipo: tuple[TotalTipo, ...]  # sujeto y no exento, facturas emitidas
    base_isp: Decimal
    cuota_isp: Decimal  # devengada por inversión del sujeto pasivo
    total_devengado: Decimal
    base_deducible_interior: Decimal  # bases de las facturas recibidas con deducción
    cuota_deducible_interior: Decimal
    cuota_deducible_isp: Decimal
    total_deducible: Decimal
    resultado: Decimal  # devengado − deducible
    base_exenta_emitida: Decimal  # informativo: no devenga IVA
    base_no_sujeta_emitida: Decimal  # informativo: no sujetas y de localización
    facturas_incluidas: tuple[int, ...]  # fuentes: ids de las facturas que suman
    sin_efecto: tuple[int, ...]  # recibidas sin IVA español (exentas, no sujetas)
    no_deducidas: tuple[Motivo, ...]  # suman 0 en deducible; motivo claro
    pendientes: tuple[Motivo, ...]  # no suman: necesitan confirmación de Gonzalo
    supuestos: tuple[str, ...]
    reglas: tuple[Regla, ...]


def normalizar_nif(nif: str) -> str:
    n = nif.strip().upper().replace("-", "").replace(" ", "")
    return n[2:] if n.startswith("ES") and len(n) == 11 else n


def _redondear(importe: Decimal) -> Decimal:
    return importe.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _trimestre_de(f: Factura) -> tuple[int, int]:
    return f.fecha.year, (f.fecha.month - 1) // 3 + 1


def calcular_303(
    facturas: Iterable[Factura],
    anio: int,
    trimestre: int,
    titular_nif: str,
    deducciones: Mapping[int, DatosDeduccion] | None = None,
    tipo_isp: Decimal = Decimal("21"),
) -> Resultado303:
    """Calcula el 303 de un trimestre.

    ``deducciones`` asocia el id de cada factura recibida con lo que el usuario
    declara (afectación, si es simplificada). ``tipo_isp`` es el tipo del IVA
    español que se aplica a la inversión del sujeto pasivo.
    """
    if trimestre not in (1, 2, 3, 4):
        raise ValueError("El trimestre debe ser 1, 2, 3 o 4.")
    if not titular_nif.strip():
        raise ValueError("Hace falta el NIF del titular para decidir qué se deduce.")
    deducciones = deducciones or {}
    titular = normalizar_nif(titular_nif)
    todas = [f for f in facturas if _trimestre_de(f) == (anio, trimestre)]
    for f in todas:
        if f.id is None:
            raise ValueError("Toda factura del cálculo debe estar guardada (con id).")
    confirmadas = {f.id for f in para_calculo(todas)}

    por_tipo: dict[Decimal, list[Decimal]] = {}
    base_isp = cuota_isp = ded_isp = Decimal(0)
    base_int = ded_int = Decimal(0)
    base_exenta = base_no_sujeta = Decimal(0)
    incluidas: list[int] = []
    sin_efecto: list[int] = []
    no_deducidas: list[Motivo] = []
    pendientes: list[Motivo] = []
    usadas: set[str] = set()
    isp_usada = False

    for f in sorted(todas, key=lambda x: (x.fecha, x.id)):
        fid = f.id
        assert fid is not None
        if fid not in confirmadas:
            pendientes.append(Motivo(fid, "factura sin confirmar: no entra en el cálculo"))
            continue
        clas = (f.clasificacion_iva or "").strip()
        if clas in _EXENTAS_O_NO_SUJETAS:
            if f.tipo == EMITIDA:
                total = sum((l.base for l in f.lineas), Decimal(0))
                if clas == "exenta":
                    base_exenta += total
                else:
                    base_no_sujeta += total
                incluidas.append(fid)
            else:
                sin_efecto.append(fid)
            continue

        if f.tipo == EMITIDA:
            if clas not in _TIPOS_NORMALES:
                pendientes.append(Motivo(fid, f"clasificación «{clas}» no tratada en una factura emitida"))
                continue
            for l in f.lineas:
                acum = por_tipo.setdefault(l.tipo_iva, [Decimal(0), Decimal(0)])
                acum[0] += l.base
                acum[1] += l.cuota
            usadas.add("cuota_devengada")
            incluidas.append(fid)
            continue

        # Facturas recibidas: necesitan lo que declara el usuario.
        datos = deducciones.get(fid)
        if clas not in _TIPOS_NORMALES and clas != "isp":
            pendientes.append(Motivo(fid, f"clasificación «{clas}» no tratada en una factura recibida"))
            continue
        if datos is None:
            pendientes.append(Motivo(
                fid, "falta indicar si el gasto está afecto a la actividad (art. 95 LIVA)"))
            continue
        proporcion = PROPORCION_AFECTACION[datos.afectacion]
        usadas.update({"afectacion", "deduccion_cuotas"})
        if datos.afectacion == AFECTACION_VEHICULO:
            usadas.add("vehiculos_50")

        if clas == "isp":
            base = sum((l.base for l in f.lineas), Decimal(0))
            cuota = _redondear(base * tipo_isp / 100)
            base_isp += base
            cuota_isp += cuota
            ded_isp += _redondear(cuota * proporcion)
            usadas.add("deduccion_isp")
            isp_usada = True
            incluidas.append(fid)
            continue

        # Recibida con IVA español: requisitos formales (art. 97 y Reglamento de facturación).
        usadas.add("requisitos_formales")
        if normalizar_nif(f.receptor_nif) != titular:
            no_deducidas.append(Motivo(
                fid, "la factura no está a nombre del titular con su NIF: no permite deducir"))
            continue
        if datos.simplificada:
            usadas.add("factura_simplificada")
            if any(l.tipo_iva > 0 and l.cuota == 0 for l in f.lineas):
                no_deducidas.append(Motivo(
                    fid, "factura simplificada sin la cuota desglosada: no permite deducir"))
                continue
        cuota = sum((l.cuota for l in f.lineas), Decimal(0))
        base_int += sum((l.base for l in f.lineas), Decimal(0))
        ded_int += _redondear(cuota * proporcion)
        if proporcion == 0:
            no_deducidas.append(Motivo(fid, "gasto declarado como no afecto a la actividad"))
        incluidas.append(fid)

    supuestos = []
    if isp_usada:
        usadas.update(_REGLAS_EXTERNAS)
        supuestos.append(
            f"Inversión del sujeto pasivo calculada al {tipo_isp} % (la factura no trae el "
            "tipo del IVA español).")
    devengado = tuple(
        TotalTipo(t, v[0], v[1]) for t, v in sorted(por_tipo.items(), reverse=True))
    total_dev = sum((t.cuota for t in devengado), Decimal(0)) + cuota_isp
    total_ded = ded_int + ded_isp
    reglas = tuple(
        (REGLAS.get(i) or REGLAS_CLASIFICACION[i]) for i in sorted(usadas))
    return Resultado303(
        anio=anio, trimestre=trimestre,
        devengado_por_tipo=devengado, base_isp=base_isp, cuota_isp=cuota_isp,
        total_devengado=total_dev,
        base_deducible_interior=base_int, cuota_deducible_interior=ded_int,
        cuota_deducible_isp=ded_isp, total_deducible=total_ded,
        resultado=total_dev - total_ded,
        base_exenta_emitida=base_exenta, base_no_sujeta_emitida=base_no_sujeta,
        facturas_incluidas=tuple(incluidas), sin_efecto=tuple(sin_efecto),
        no_deducidas=tuple(no_deducidas), pendientes=tuple(pendientes),
        supuestos=tuple(supuestos), reglas=reglas,
    )
