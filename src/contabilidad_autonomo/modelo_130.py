"""Cálculo del modelo 130 trimestral con comprobación de exención (v1, issue #29).

Código puro y determinista (principio 1 de CLAUDE.md): recibe facturas y
devuelve importes con ``Decimal``. No presenta nada ni asigna casillas del
formulario (la correspondencia con las casillas no se ha contrastado).

Cálculo (art. 110.1.a y 110.3.a RIRPF, estimación directa):

    rendimiento neto acumulado = ingresos − gastos deducibles
                                 (del 1 de enero al último día del trimestre)
    pago = 20 % del rendimiento neto acumulado
           − pagos fraccionados de los trimestres anteriores del año
           − retenciones soportadas acumuladas del año
    a ingresar = el pago si es positivo; si no, 0

Qué entra:

* Solo facturas **confirmadas** (``pendientes.para_calculo``) con fecha entre
  el 1 de enero y el último día del trimestre. Las pendientes no suman: salen
  en ``pendientes`` y el resultado queda marcado ``incompleto``.
* **Ingresos**: suma de las bases de las facturas emitidas (sin IVA).
* **Retenciones**: ``retencion_irpf`` de las facturas emitidas.
* **Gastos**: base de las facturas recibidas multiplicada por la proporción
  deducible que el usuario declara en ``proporcion_gasto`` (por id de factura,
  entre 0 y 1). Si no consta para una recibida confirmada, la factura **no
  suma**, sale en ``sin_datos_gasto`` y el resultado queda ``incompleto``
  (nunca se adivina).
* **Pagos de trimestres anteriores**: si no se indican (``pagos_anteriores``),
  se calculan encadenando los trimestres anteriores con estas mismas reglas.

Exención (art. 109.2 y 109.5 RIRPF): quien ejerce una actividad profesional no
está obligado si en el año natural anterior al menos el 70 % de los ingresos
de la actividad fue objeto de retención o ingreso a cuenta. Se calcula con las
facturas emitidas confirmadas del año anterior (``facturas_anio_anterior``).
El resultado es «no lo sé» (``estado = NO_SE``, ``a_ingresar = None``) si:

* no se aportan las facturas del año anterior (``None``);
* el año anterior no tuvo ingresos (posible inicio de actividad, art. 109.5:
  se miraría el porcentaje del periodo en curso, que aquí no se decide);
* el año anterior tiene facturas pendientes de confirmar (podrían cambiar el
  porcentaje).

Si la actividad no es profesional (``actividad_profesional=False``), el
art. 109.2 no da exención y se calcula el pago. Para actividades agrícolas,
ganaderas o forestales (art. 109.3 y 109.4) y estimación objetiva no hay
cálculo: este módulo solo cubre estimación directa.

Supuestos (se anotan también en ``supuestos``):

* La fecha de la factura es la de imputación del ingreso o gasto.
* Con rendimiento neto acumulado negativo, el 20 % es 0 (no se contrastó con
  las instrucciones del formulario).
* El 20 % se redondea al céntimo, mitad hacia arriba, una sola vez.
* Una retención o un pago anterior mayor que el 20 % no devuelve nada en el
  trimestre: ``a_ingresar`` es 0 y ``resultado_bruto`` conserva el valor
  negativo (informativo; el acumulado del siguiente trimestre ya lo recoge).

Límites conocidos (no se resuelven aquí):

* Minoración por rendimientos netos bajos del año anterior (art. 110.3.c) y
  deducción por vivienda habitual con financiación ajena (art. 110.3.d): no se
  aplican, así que el pago puede salir mayor que el real.
* Gastos sin factura (cuota de autónomos, amortizaciones, gastos de difícil
  justificación): no se pueden declarar todavía. Mismo efecto: pago mayor.
* Solo se suma la base de las facturas recibidas: la cuota de IVA que no se
  pueda deducir y que formaría parte del gasto no se suma.
* Estimación objetiva, actividades agrícolas, ganaderas o forestales y
  arrendamientos como actividad económica.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from contabilidad_autonomo.clasificacion_iva import Regla
from contabilidad_autonomo.facturas import EMITIDA, PENDIENTE, RECIBIDA, Factura
from contabilidad_autonomo.pendientes import para_calculo

FECHA_CONTRASTE = date(2026, 11, 6)  # consulta de www.boe.es (ver reglas)

CALCULADO = "calculado"
EXENTO = "exento"
NO_SE = "no_se"

_RIRPF = "Real Decreto 439/2007 (Reglamento del IRPF)"
PORCENTAJE_PAGO = Decimal("0.20")
PORCENTAJE_EXENCION = Decimal("70")
ANIO_MINIMO = 2019  # art. 110 en vigor desde 2018-12-23 (ver REGLAS)


def _r(id_: str, articulo: str, desde: date, descripcion: str) -> Regla:
    return Regla(id_, _RIRPF, articulo, desde, None, descripcion)


REGLAS: dict[str, Regla] = {r.id: r for r in (
    _r("exencion_70", "art. 109.2 y 109.5", date(2007, 4, 1),
       "Quien ejerce actividades profesionales no está obligado al pago "
       "fraccionado si en el año natural anterior al menos el 70 % de los "
       "ingresos de la actividad fue objeto de retención o ingreso a cuenta; en "
       "inicio de actividad se mira el porcentaje del periodo en curso. "
       "Contrastado en BOE (BOE-A-2007-6820) el 2026-11-06: el texto consolidado "
       "no muestra modificaciones del art. 109; fecha = entrada en vigor del "
       "texto original del reglamento (2007-04-01), no comprobada versión a "
       "versión."),
    _r("pago_20", "art. 110.1.a", date(2018, 12, 23),
       "Estimación directa: 20 % del rendimiento neto del periodo desde el 1 de "
       "enero hasta el último día del trimestre, menos los pagos fraccionados "
       "de los trimestres anteriores del año. Contrastado en BOE el "
       "2026-11-06. Fecha: última actualización del art. 110 (en vigor desde "
       "2018-12-23, RD 1461/2018); el 20 % no se comprobó versión a versión."),
    _r("retenciones", "art. 110.3.a", date(2018, 12, 23),
       "En actividades profesionales en estimación directa se deducen las "
       "retenciones e ingresos a cuenta soportados desde el 1 de enero hasta el "
       "último día del trimestre. Contrastado en BOE el 2026-11-06. Fecha: "
       "última actualización del art. 110 (2018-12-23)."),
)}


@dataclass(frozen=True)
class Exencion:
    """``exento``: True / False / None («no lo sé»)."""
    exento: bool | None
    motivo: str
    ingresos_anio_anterior: Decimal | None = None
    ingresos_con_retencion: Decimal | None = None


@dataclass(frozen=True)
class Resultado130:
    anio: int
    trimestre: int
    estado: str  # CALCULADO, EXENTO o NO_SE
    exencion: Exencion
    ingresos: Decimal
    gastos: Decimal
    rendimiento_neto: Decimal
    veinte_por_ciento: Decimal
    pagos_anteriores: Decimal
    retenciones: Decimal
    resultado_bruto: Decimal
    a_ingresar: Decimal | None  # None = «no lo sé»
    facturas_ingresos: tuple[int | None, ...]
    facturas_gastos: tuple[int | None, ...]
    pendientes: tuple[int | None, ...]
    sin_datos_gasto: tuple[int | None, ...]
    supuestos: tuple[str, ...]
    reglas: tuple[Regla, ...] = field(default_factory=tuple)

    @property
    def incompleto(self) -> bool:
        """Hay facturas que no han entrado y podrían cambiar el resultado."""
        return bool(self.pendientes or self.sin_datos_gasto)


def _centimo(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _base(f: Factura) -> Decimal:
    return sum((l.base for l in f.lineas), Decimal(0))


def _fin_trimestre(anio: int, trimestre: int) -> date:
    return date(anio + 1, 1, 1) if trimestre == 4 else date(anio, 3 * trimestre + 1, 1)


def _en_periodo(f: Factura, anio: int, trimestre: int) -> bool:
    """Del 1 de enero al último día del trimestre (``fecha`` < inicio del siguiente)."""
    return date(anio, 1, 1) <= f.fecha < _fin_trimestre(anio, trimestre)


@dataclass(frozen=True)
class _Acumulado:
    ingresos: Decimal
    gastos: Decimal
    retenciones: Decimal
    ids_ingresos: tuple
    ids_gastos: tuple
    pendientes: tuple
    sin_datos: tuple

    @property
    def rendimiento(self) -> Decimal:
        return self.ingresos - self.gastos

    @property
    def veinte(self) -> Decimal:
        return _centimo(max(self.rendimiento, Decimal(0)) * PORCENTAJE_PAGO)


def _acumular(facturas: Iterable[Factura], anio: int, trimestre: int,
              proporcion: Mapping[int, Decimal]) -> _Acumulado:
    todas = [f for f in facturas if _en_periodo(f, anio, trimestre)]
    pendientes = tuple(f.id for f in todas if f.estado == PENDIENTE)
    ingresos = gastos = retenciones = Decimal(0)
    ids_i, ids_g, sin = [], [], []
    for f in para_calculo(todas):
        if f.tipo == EMITIDA:
            ingresos += _base(f)
            retenciones += f.retencion_irpf
            ids_i.append(f.id)
        elif f.tipo == RECIBIDA:
            p = proporcion.get(f.id) if f.id is not None else None
            if p is None:
                sin.append(f.id)
                continue
            gastos += _centimo(_base(f) * p)
            ids_g.append(f.id)
    return _Acumulado(ingresos, gastos, retenciones, tuple(ids_i), tuple(ids_g),
                      pendientes, tuple(sin))


def comprobar_exencion(
    facturas_anio_anterior: Iterable[Factura] | None,
    anio_anterior: int,
    *,
    actividad_profesional: bool,
) -> Exencion:
    """Art. 109.2 y 109.5 RIRPF: ¿al menos el 70 % de los ingresos llevó retención?"""
    if not actividad_profesional:
        return Exencion(False, "la exención del art. 109.2 es solo para actividades "
                               "profesionales")
    if facturas_anio_anterior is None:
        return Exencion(None, "no se han aportado las facturas del año anterior")
    del_anio = [f for f in facturas_anio_anterior if f.fecha.year == anio_anterior]
    if any(f.estado == PENDIENTE for f in del_anio):
        return Exencion(None, "hay facturas del año anterior pendientes de confirmar; "
                              "podrían cambiar el porcentaje")
    emitidas = [f for f in para_calculo(del_anio) if f.tipo == EMITIDA]
    total = sum((_base(f) for f in emitidas), Decimal(0))
    con_ret = sum((_base(f) for f in emitidas if f.retencion_irpf > 0), Decimal(0))
    if total <= 0:
        return Exencion(None, "sin ingresos el año anterior (posible inicio de "
                              "actividad, art. 109.5): no se puede decidir",
                        total, con_ret)
    exento = con_ret * 100 >= PORCENTAJE_EXENCION * total
    pct = (con_ret * 100 / total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Exencion(exento,
                    f"{pct} % de los ingresos del año anterior con retención "
                    f"(mínimo {PORCENTAJE_EXENCION} %)", total, con_ret)


def calcular_130(
    facturas: Iterable[Factura],
    anio: int,
    trimestre: int,
    *,
    proporcion_gasto: Mapping[int, Decimal],
    facturas_anio_anterior: Iterable[Factura] | None,
    actividad_profesional: bool,
    pagos_anteriores: Decimal | None = None,
) -> Resultado130:
    """Modelo 130 del ``trimestre`` (1-4) de ``anio``. Ver la cabecera del módulo."""
    if trimestre not in (1, 2, 3, 4):
        raise ValueError("El trimestre debe ser 1, 2, 3 o 4.")
    if anio < ANIO_MINIMO:
        raise ValueError(f"Las reglas contrastadas valen desde {ANIO_MINIMO}.")
    facturas = list(facturas)
    for p in proporcion_gasto.values():
        if not (Decimal(0) <= p <= Decimal(1)):
            raise ValueError("La proporción deducible debe estar entre 0 y 1.")
    if pagos_anteriores is not None and pagos_anteriores < 0:
        raise ValueError("Los pagos anteriores no pueden ser negativos.")

    supuestos = [
        "Fecha de la factura = fecha de imputación del ingreso o gasto.",
        "Estimación directa; sin minoración del art. 110.3.c ni deducción del "
        "art. 110.3.d.",
        "Gastos = base de las facturas recibidas por la proporción declarada; sin "
        "gastos sin factura.",
    ]
    ac = _acumular(facturas, anio, trimestre, proporcion_gasto)

    if pagos_anteriores is None:
        previos = Decimal(0)
        for q in range(1, trimestre):
            aq = _acumular(facturas, anio, q, proporcion_gasto)
            previos += max(Decimal(0), aq.veinte - previos - aq.retenciones)
        if trimestre > 1:
            supuestos.append("Pagos de trimestres anteriores calculados con estas "
                             "mismas reglas (no se indicaron los ingresados).")
    else:
        previos = pagos_anteriores
        supuestos.append("Pagos de trimestres anteriores indicados por el usuario.")

    bruto = ac.veinte - previos - ac.retenciones
    exencion = comprobar_exencion(facturas_anio_anterior, anio - 1,
                                  actividad_profesional=actividad_profesional)
    if exencion.exento is None:
        estado, a_ingresar = NO_SE, None
    elif exencion.exento:
        estado, a_ingresar = EXENTO, Decimal(0)
    else:
        estado, a_ingresar = CALCULADO, max(Decimal(0), bruto)
    if ac.rendimiento < 0:
        supuestos.append("Rendimiento neto negativo: el 20 % se toma como 0.")

    return Resultado130(
        anio, trimestre, estado, exencion, ac.ingresos, ac.gastos, ac.rendimiento,
        ac.veinte, previos, ac.retenciones, bruto, a_ingresar, ac.ids_ingresos,
        ac.ids_gastos, ac.pendientes, ac.sin_datos, tuple(supuestos),
        tuple(REGLAS.values()),
    )
