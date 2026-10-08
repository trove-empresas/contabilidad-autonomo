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

* Fecha de devengo = fecha de la factura salvo que se indique otra por factura
  (``fechas_devengo``); el art. 75 LIVA no se ha contrastado. Facturas
  recibidas: el IVA soportado se deduce en el trimestre en que se recibe la
  factura (art. 99.Cuatro) o en los siguientes, dentro de 4 años desde que
  nace el derecho (arts. 98.Uno y 99.Tres, contrastados el ``FECHA_CONTRASTE``).
  El 4.º año se comprueba contra el final del trimestre, no contra la fecha real
  de presentación (más estricto, nunca más laxo).
* Prorrata, regularización de bienes de inversión, recargo de equivalencia,
  regímenes especiales, compensación de cuotas de periodos anteriores,
  adquisiciones intracomunitarias de bienes e importaciones.
* ISP: la factura no trae el tipo del IVA español, así que se asume el tipo
  general (``tipo_isp``, 21 % por defecto, art. 90.Uno LIVA) salvo que se
  indique otro por factura (``DatosDeduccion.tipo_isp``). Solo se admiten los
  tipos 21, 10 y 4 %; con otro valor la factura queda pendiente. La ISP exige
  que la factura esté a nombre del titular o de su negocio (``nifs_negocio``);
  si no, queda pendiente. El resultado anota el supuesto en ``supuestos``.
* Redondeo: las cuotas de las facturas se suman tal cual constan, sin
  recalcularlas (``pendientes`` ya comprueba que cuadran). Solo se calcula y
  se redondea al céntimo (mitad hacia arriba), factura a factura, la cuota de
  la ISP y la parte deducible cuando la afectación no es total (p. ej. 50 %
  de una cuota impar de céntimos), para no dejar fracciones de céntimo.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
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
TIPOS_ISP = (Decimal(21), Decimal(10), Decimal(4))  # art. 90.Uno y 91.Uno y Dos LIVA
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
    _r("plazo_deduccion", _LIVA, "arts. 98.Uno, 99.Tres y Cuatro y 100", date(2012, 10, 31),
       "El derecho a deducir nace al devengarse la cuota (art. 98.Uno); las cuotas se "
       "entienden soportadas al recibir la factura (art. 99.Cuatro) y pueden "
       "deducirse en ese periodo o en los sucesivos, hasta 4 años desde que nace el "
       "derecho (art. 99.Tres); pasado el plazo, caduca (art. 100). Fecha: última "
       "actualización del art. 99 (en vigor desde 2012-10-31). Contrastado en BOE "
       "2026-10-07."),
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
    tipo_isp: Decimal | None = None  # tipo del IVA español en la ISP de esta factura
    fecha_recepcion: date | None = None  # cuándo se recibió la factura (por defecto, su fecha)
    deducir_en: tuple[int, int] | None = None  # (año, trimestre) elegido, si es posterior

    def __post_init__(self) -> None:
        if self.afectacion not in PROPORCION_AFECTACION:
            raise ValueError(f"Afectación desconocida: {self.afectacion!r}")
        if self.deducir_en is not None and self.deducir_en[1] not in (1, 2, 3, 4):
            raise ValueError("deducir_en debe ser (año, trimestre) con trimestre de 1 a 4.")


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
    de_periodos_anteriores: tuple[int, ...]  # recibidas deducidas ahora, soportadas antes
    supuestos: tuple[str, ...]
    reglas: tuple[Regla, ...]


def normalizar_nif(nif: str) -> str:
    n = nif.strip().upper().replace("-", "").replace(" ", "")
    return n[2:] if n.startswith("ES") and len(n) == 11 else n


def _redondear(importe: Decimal) -> Decimal:
    return importe.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _trimestre_de(dia: date) -> tuple[int, int]:
    return dia.year, (dia.month - 1) // 3 + 1


def _fin_trimestre(anio: int, trimestre: int) -> date:
    inicio_siguiente = date(anio + (trimestre == 4), 1 if trimestre == 4 else trimestre * 3 + 1, 1)
    return inicio_siguiente - timedelta(days=1)


def _mas_cuatro_anios(dia: date) -> date:
    try:
        return dia.replace(year=dia.year + 4)
    except ValueError:  # 29 de febrero
        return dia.replace(year=dia.year + 4, day=28)


def calcular_303(
    facturas: Iterable[Factura],
    anio: int,
    trimestre: int,
    titular_nif: str,
    deducciones: Mapping[int, DatosDeduccion] | None = None,
    tipo_isp: Decimal = Decimal("21"),
    fechas_devengo: Mapping[int, date] | None = None,
    nifs_negocio: Iterable[str] = (),
) -> Resultado303:
    """Calcula el 303 de un trimestre.

    ``deducciones`` asocia el id de cada factura recibida con lo que el usuario
    declara (afectación, si es simplificada). ``tipo_isp`` es el tipo del IVA
    español que se aplica por defecto a la inversión del sujeto pasivo.
    ``fechas_devengo`` corrige por factura la fecha de devengo (por defecto, la
    de la factura). ``nifs_negocio`` son otros NIF a cuyo nombre puede estar una
    factura de ISP además del titular.

    Se puede pasar cualquier factura: entran las emitidas devengadas en el
    trimestre y las recibidas cuyo trimestre de deducción es este (el de su
    recepción, o el que el usuario eligió con ``deducir_en``).
    """
    if trimestre not in (1, 2, 3, 4):
        raise ValueError("El trimestre debe ser 1, 2, 3 o 4.")
    if not titular_nif.strip():
        raise ValueError("Hace falta el NIF del titular para decidir qué se deduce.")
    deducciones = deducciones or {}
    fechas_devengo = fechas_devengo or {}
    titular = normalizar_nif(titular_nif)
    propios = {titular} | {normalizar_nif(n) for n in nifs_negocio if n.strip()}
    facturas = list(facturas)
    for f in facturas:
        if f.id is None:
            raise ValueError("Toda factura del cálculo debe estar guardada (con id).")
    periodo = (anio, trimestre)
    todas: list[Factura] = []
    anteriores: list[int] = []
    fuera_de_plazo: list[Motivo] = []
    aplazadas: list[Motivo] = []
    for f in facturas:
        devengo = fechas_devengo.get(f.id, f.fecha)
        if f.tipo == EMITIDA:
            if _trimestre_de(devengo) == periodo:
                todas.append(f)
            continue
        datos_f = deducciones.get(f.id)
        recepcion = datos_f.fecha_recepcion if datos_f and datos_f.fecha_recepcion else f.fecha
        natural = _trimestre_de(max(devengo, recepcion))  # art. 99.Cuatro
        elegido = datos_f.deducir_en if datos_f and datos_f.deducir_en else natural
        if elegido < natural:
            if elegido == periodo:
                aplazadas.append(Motivo(
                    f.id, "se pide deducir antes de que el IVA esté soportado (art. 99.Cuatro)"))
            continue
        if elegido != periodo:
            continue
        if _fin_trimestre(*periodo) > _mas_cuatro_anios(devengo):
            fuera_de_plazo.append(Motivo(
                f.id, "han pasado más de 4 años desde que nació el derecho a deducir "
                "(arts. 99.Tres y 100): no se puede deducir"))
            continue
        todas.append(f)
        if natural != periodo:
            anteriores.append(f.id)
    confirmadas = {f.id for f in para_calculo(todas)}

    por_tipo: dict[Decimal, list[Decimal]] = {}
    base_isp = cuota_isp = ded_isp = Decimal(0)
    base_int = ded_int = Decimal(0)
    base_exenta = base_no_sujeta = Decimal(0)
    incluidas: list[int] = []
    sin_efecto: list[int] = []
    no_deducidas: list[Motivo] = list(fuera_de_plazo)
    pendientes: list[Motivo] = list(aplazadas)
    usadas: set[str] = set()
    isp_usada = False
    tipos_isp_usados: set[Decimal] = set()

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
            tipo = datos.tipo_isp if datos.tipo_isp is not None else tipo_isp
            if tipo not in TIPOS_ISP:
                pendientes.append(Motivo(
                    fid, f"tipo de IVA {tipo} % dudoso en la inversión del sujeto pasivo: "
                    "indica el tipo (21, 10 o 4 %)"))
                continue
            if normalizar_nif(f.receptor_nif) not in propios:
                pendientes.append(Motivo(
                    fid, "la factura de inversión del sujeto pasivo no consta a nombre del "
                    "titular ni de su negocio"))
                continue
            tipos_isp_usados.add(tipo)
            base = sum((l.base for l in f.lineas), Decimal(0))
            cuota = _redondear(base * tipo / 100)
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
    if anteriores:
        usadas.add("plazo_deduccion")
    if isp_usada:
        usadas.update(_REGLAS_EXTERNAS)
        tipos = ", ".join(f"{t} %" for t in sorted(tipos_isp_usados, reverse=True))
        supuestos.append(
            f"Inversión del sujeto pasivo calculada al {tipos} (la factura no trae el "
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
        de_periodos_anteriores=tuple(anteriores),
        supuestos=tuple(supuestos), reglas=reglas,
    )
