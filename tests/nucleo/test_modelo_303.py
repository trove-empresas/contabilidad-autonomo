"""Pruebas del cálculo del modelo 303 (issue #12). Solo datos ficticios.

Los casos de ``docs/casos_propuestos/modelo_303.json`` son PROPUESTAS de un
agente, pendientes de que Gonzalo las valide; no están en ``casos_validados/``.
"""

import json
import pathlib
from datetime import date
from decimal import Decimal as D

import pytest

from contabilidad_autonomo import modelo_303 as m
from contabilidad_autonomo.facturas import Factura, LineaIva

RAIZ = pathlib.Path(__file__).resolve().parents[2]
PROPUESTAS = json.loads((RAIZ / "docs/casos_propuestos/modelo_303.json").read_text(encoding="utf-8"))


def _factura(d: dict) -> Factura:
    return Factura(
        tipo=d["tipo"], emisor_nombre="Ficticia S.L.", emisor_nif=d["emisor_nif"],
        receptor_nombre="Titular Ficticio", receptor_nif=d["receptor_nif"],
        fecha=date.fromisoformat(d["fecha"]), numero=f"F-{d['id']}", total=D(0),
        confianza_extraccion=D("0.99"),
        lineas=tuple(LineaIva(D(b), D(t), D(c)) for b, t, c in d["lineas"]),
        clasificacion_iva=d["clasificacion_iva"], estado=d["estado"], id=d["id"])


def _calcular(caso: dict) -> m.Resultado303:
    ded = {int(k): m.DatosDeduccion(**v) for k, v in caso["deducciones"].items()}
    extra = {"tipo_isp": D(caso["tipo_isp"])} if "tipo_isp" in caso else {}
    return m.calcular_303([_factura(f) for f in caso["facturas"]], PROPUESTAS["anio"],
                          PROPUESTAS["trimestre"], PROPUESTAS["titular_nif"], ded, **extra)


@pytest.mark.parametrize("caso", PROPUESTAS["casos"], ids=lambda c: c["situacion"][:60])
def test_casos_propuestos(caso):
    r = _calcular(caso)
    esp = caso["esperado"]
    for campo in ("total_devengado", "total_deducible", "resultado", "base_isp", "cuota_isp",
                  "base_exenta_emitida", "base_no_sujeta_emitida"):
        if campo in esp:
            assert getattr(r, campo) == D(esp[campo]), campo
    if "devengado_por_tipo" in esp:
        real = [{"tipo_iva": str(t.tipo_iva), "base": str(t.base), "cuota": str(t.cuota)}
                for t in r.devengado_por_tipo]
        assert real == esp["devengado_por_tipo"]
    if "no_deducidas" in esp:
        assert [x.factura_id for x in r.no_deducidas] == esp["no_deducidas"]
    if "pendientes" in esp:
        assert [x.factura_id for x in r.pendientes] == esp["pendientes"]
    if "facturas_incluidas" in esp:
        assert list(r.facturas_incluidas) == esp["facturas_incluidas"]
    # Las pendientes nunca se incluyen, y nada se incluye dos veces.
    assert not {x.factura_id for x in r.pendientes} & set(r.facturas_incluidas)
    assert len(set(r.facturas_incluidas)) == len(r.facturas_incluidas)


def test_toda_regla_lleva_norma_articulo_y_fecha():
    for r in m.REGLAS.values():
        assert r.norma.strip() and r.articulo.strip() and isinstance(r.desde, date), r.id


def test_el_resultado_cita_las_reglas_usadas():
    caso = next(c for c in PROPUESTAS["casos"] if c["situacion"].startswith("Servicio de software"))
    ids = {r.id for r in _calcular(caso).reglas}
    assert {"isp_servicios", "tipo_general", "deduccion_isp", "afectacion"} <= ids
    assert _calcular(caso).supuestos  # el tipo de la ISP queda anotado como supuesto


def test_el_titular_se_compara_sin_prefijo_ni_guiones():
    assert m.normalizar_nif("ES-87654321x") == "87654321X"
    caso = next(c for c in PROPUESTAS["casos"] if c["situacion"].startswith("Simplificada con mis datos y la"))
    caso["facturas"][0]["receptor_nif"] = "ES87654321X"
    assert _calcular(caso).total_deducible == D("21.00")


def test_datos_invalidos_se_rechazan():
    with pytest.raises(ValueError):
        m.DatosDeduccion("casi")
    with pytest.raises(ValueError):
        m.calcular_303([], 2026, 5, "87654321X")
    with pytest.raises(ValueError):
        m.calcular_303([], 2026, 2, "  ")
    sin_id = _factura(PROPUESTAS["casos"][0]["facturas"][0])
    with pytest.raises(ValueError):
        m.calcular_303([Factura(**{**sin_id.__dict__, "id": None})], 2026, 2, "87654321X")


def test_sin_facturas_todo_es_cero():
    r = m.calcular_303([], 2026, 1, "87654321X")
    assert r.total_devengado == r.total_deducible == r.resultado == D(0)
    assert r.devengado_por_tipo == ()


def test_no_se_usan_float():
    r = _calcular(PROPUESTAS["casos"][2] | {"deducciones": {"2": {"afectacion": "vehiculo_50"}}})
    for campo in ("total_devengado", "total_deducible", "resultado"):
        assert isinstance(getattr(r, campo), D)
