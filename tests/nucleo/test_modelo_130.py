"""Pruebas del modelo 130 (issue #29). Solo facturas ficticias.

Los casos de ``docs/casos_propuestos/modelo_130.json`` son propuestas del
agente, no casos validados por Gonzalo.
"""

import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from contabilidad_autonomo import facturas as fa
from contabilidad_autonomo import modelo_130 as m

RUTA = Path(__file__).parents[2] / "docs" / "casos_propuestos" / "modelo_130.json"
CASOS = json.loads(RUTA.read_text(encoding="utf-8"))["casos"]


def _factura(d, id_):
    tipo = d["tipo"]
    return fa.Factura(
        tipo=tipo, emisor_nombre="A", emisor_nif="12345678Z",
        receptor_nombre="B", receptor_nif="A58818501",
        fecha=date.fromisoformat(d["fecha"]), numero=f"N-{id_}",
        total=D(d["base"]), confianza_extraccion=D("0.95"),
        lineas=(fa.LineaIva(D(d["base"]), D("0"), D("0")),),
        retencion_irpf=D(d["retencion"]), estado=d["estado"], id=id_,
    )


def _ejecutar(caso):
    n = iter(range(1, 1000))
    fs, prop = [], {}
    for d in caso["facturas"]:
        f = _factura(d, next(n))
        fs.append(f)
        if "proporcion" in d:
            prop[f.id] = D(d["proporcion"])
    ant = None
    if caso["anterior"] is not None:
        ant = [_factura(d, next(n)) for d in caso["anterior"]]
    pagos = None if caso["pagos_anteriores"] is None else D(caso["pagos_anteriores"])
    return m.calcular_130(
        fs, caso["anio"], caso["trimestre"], proporcion_gasto=prop,
        facturas_anio_anterior=ant,
        actividad_profesional=caso["actividad_profesional"], pagos_anteriores=pagos)


def test_hay_casos_propuestos():
    assert len(CASOS) >= 15


@pytest.mark.parametrize("caso", CASOS, ids=[c["situacion"][:60] for c in CASOS])
def test_los_casos_propuestos_se_cumplen_con_el_codigo(caso):
    r = _ejecutar(caso)
    for clave, esperado in caso["esperado"].items():
        if clave in ("pendientes", "sin_datos_gasto"):
            real = len(getattr(r, clave))
        else:
            real = getattr(r, clave)
        if isinstance(esperado, str) and clave not in ("estado",):
            esperado = D(esperado)
        assert real == esperado, f"{clave}: {real!r} != {esperado!r}"


def test_el_resultado_usa_decimal_y_no_float():
    r = _ejecutar(CASOS[0])
    for campo in ("ingresos", "gastos", "rendimiento_neto", "veinte_por_ciento",
                  "pagos_anteriores", "retenciones", "resultado_bruto", "a_ingresar"):
        assert isinstance(getattr(r, campo), D), campo


def test_cada_regla_cita_norma_articulo_y_fecha():
    assert m.REGLAS
    for regla in m.REGLAS.values():
        assert regla.norma.strip() and regla.articulo.strip()
        assert isinstance(regla.desde, date)
    r = _ejecutar(CASOS[0])
    assert set(r.reglas) == set(m.REGLAS.values())


def test_trimestre_invalido_falla():
    with pytest.raises(ValueError):
        m.calcular_130([], 2026, 5, proporcion_gasto={}, facturas_anio_anterior=None,
                       actividad_profesional=True)


def test_proporcion_fuera_de_rango_falla():
    with pytest.raises(ValueError):
        m.calcular_130([], 2026, 1, proporcion_gasto={1: D("1.5")},
                       facturas_anio_anterior=None, actividad_profesional=True)


def test_pagos_anteriores_negativos_fallan():
    with pytest.raises(ValueError):
        m.calcular_130([], 2026, 1, proporcion_gasto={}, facturas_anio_anterior=None,
                       actividad_profesional=True, pagos_anteriores=D("-1"))


def test_anio_sin_reglas_contrastadas_falla():
    with pytest.raises(ValueError):
        m.calcular_130([], 2018, 1, proporcion_gasto={}, facturas_anio_anterior=None,
                       actividad_profesional=True)


def test_los_ingresos_cuentan_las_bases_y_no_el_iva():
    f = fa.Factura(
        tipo=fa.EMITIDA, emisor_nombre="A", emisor_nif="12345678Z",
        receptor_nombre="B", receptor_nif="A58818501", fecha=date(2026, 2, 1),
        numero="X", total=D("121.00"), confianza_extraccion=D("0.95"),
        lineas=(fa.LineaIva(D("100.00"), D("21"), D("21.00")),),
        estado=fa.CONFIRMADA, id=1)
    r = m.calcular_130([f], 2026, 1, proporcion_gasto={}, facturas_anio_anterior=[],
                       actividad_profesional=True)
    assert r.ingresos == D("100.00")


def test_comprobar_exencion_ignora_recibidas_y_otro_anio():
    ant = [_factura({"tipo": "emitida", "fecha": "2025-02-01", "base": "1000.00",
                     "retencion": "10.00", "estado": "confirmada"}, 1),
           _factura({"tipo": "recibida", "fecha": "2025-02-01", "base": "9000.00",
                     "retencion": "0", "estado": "confirmada"}, 2),
           _factura({"tipo": "emitida", "fecha": "2024-02-01", "base": "9000.00",
                     "retencion": "0", "estado": "confirmada"}, 3)]
    e = m.comprobar_exencion(ant, 2025, actividad_profesional=True)
    assert e.exento is True and e.ingresos_anio_anterior == D("1000.00")
