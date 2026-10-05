"""Pruebas de la clasificación de IVA (issue #11). Solo datos ficticios."""

from datetime import date
from decimal import Decimal as D

import pytest

from contabilidad_autonomo import clasificacion_iva as ci
from contabilidad_autonomo import pendientes as pe

F = date(2026, 3, 10)
NIF_ES = "12345678Z"
NIF_ALEMAN = "DE123456789"
NIF_EEUU = "US12345678"  # prefijo de dos letras: país no español


def _op(**kw):
    base = dict(
        tipo="recibida", fecha=F, tipo_iva=D("21"), nif_contraparte=NIF_ES,
        es_servicio=True, operacion="sujeta",
    )
    base.update(kw)
    return ci.Operacion(**base)


# --- Referencia normativa obligatoria (principio 4 de CLAUDE.md) -----------

def test_toda_regla_lleva_norma_articulo_y_fecha():
    assert ci.REGLAS, "debe haber reglas"
    for r in ci.REGLAS.values():
        assert r.norma.strip() and r.articulo.strip(), r.id
        assert isinstance(r.desde, date), r.id
        assert r.hasta is None or r.hasta >= r.desde, r.id


def test_una_regla_sin_referencia_se_rechaza():
    with pytest.raises(ValueError):
        ci.Regla("x", "", "art. 1", date(2020, 1, 1), None, "d")
    with pytest.raises(ValueError):
        ci.Regla("x", "Ley", "  ", date(2020, 1, 1), None, "d")


def test_cada_resultado_apunta_a_una_regla_registrada():
    casos = [_op(tipo_iva=D(t)) for t in ("21", "10", "4")]
    casos += [_op(tipo_iva=D(0), nif_contraparte=NIF_ALEMAN),
              _op(tipo_iva=D(0), operacion="exenta", articulo_exencion="20.Uno.9º"),
              _op(tipo_iva=D(0), operacion="no_sujeta")]
    for op in casos:
        r = ci.clasificar(op)
        assert r.clasificacion is not None and r.regla.id in ci.REGLAS


# --- Sujeta y no exenta: tipos --------------------------------------------

@pytest.mark.parametrize("tipo, esperado", [
    ("21", "general"), ("10", "reducido"), ("4", "superreducido"),
])
def test_tipos_de_iva(tipo, esperado):
    r = ci.clasificar(_op(tipo_iva=D(tipo)))
    assert r.clasificacion == esperado


@pytest.mark.parametrize("tipo", ["5", "7", "0", "21.5", "16"])
def test_tipo_no_reconocido_en_operacion_sujeta_queda_indeterminado(tipo):
    r = ci.clasificar(_op(tipo_iva=D(tipo)))
    assert r.clasificacion is None and r.motivo


def test_sin_tipo_de_iva_queda_indeterminado():
    assert ci.clasificar(_op(tipo_iva=None)).clasificacion is None


def test_la_regla_solo_aplica_desde_su_fecha():
    # 21 % general vigente desde 2012-09-01; antes no hay regla en el código.
    assert ci.clasificar(_op(fecha=date(2012, 9, 1))).clasificacion == "general"
    assert ci.clasificar(_op(fecha=date(2012, 8, 31))).clasificacion is None


# --- Inversión del sujeto pasivo ------------------------------------------

def test_servicio_de_proveedor_extranjero_sin_iva_es_isp():
    for nif in (NIF_ALEMAN, NIF_EEUU):
        r = ci.clasificar(_op(tipo_iva=D(0), nif_contraparte=nif))
        assert r.clasificacion == "isp"
        assert "84" in r.regla.articulo


def test_proveedor_extranjero_con_iva_espanol_es_incoherente():
    r = ci.clasificar(_op(tipo_iva=D("21"), nif_contraparte=NIF_ALEMAN))
    assert r.clasificacion is None and "extranjera" in r.motivo


def test_proveedor_extranjero_pais_explicito_prevalece_sobre_el_nif():
    r = ci.clasificar(_op(tipo_iva=D(0), nif_contraparte="", pais_contraparte="FR"))
    assert r.clasificacion == "isp"


def test_entrega_de_bienes_extranjera_no_es_isp_de_servicios():
    r = ci.clasificar(_op(tipo_iva=D(0), nif_contraparte=NIF_ALEMAN, es_servicio=False))
    assert r.clasificacion is None


def test_proveedor_sin_pais_identificable_queda_indeterminado_si_no_hay_iva():
    r = ci.clasificar(_op(tipo_iva=D(0), nif_contraparte="???"))
    assert r.clasificacion is None


# --- Exenta y no sujeta ----------------------------------------------------

def test_exenta_exige_declararla_con_su_apartado_del_art_20():
    r = ci.clasificar(_op(tipo_iva=D(0), operacion="exenta", articulo_exencion="20.Uno.9º"))
    assert r.clasificacion == "exenta" and r.regla.articulo.startswith("art. 20")
    sin = ci.clasificar(_op(tipo_iva=D(0), operacion="exenta"))
    assert sin.clasificacion is None


def test_exenta_con_iva_repercutido_es_incoherente():
    r = ci.clasificar(_op(tipo_iva=D("21"), operacion="exenta", articulo_exencion="20.Uno.9º"))
    assert r.clasificacion is None


def test_no_sujeta_declarada_sin_iva():
    r = ci.clasificar(_op(tipo_iva=D(0), operacion="no_sujeta"))
    assert r.clasificacion == "no_sujeta" and r.regla.articulo.startswith("art. 7")


def test_no_sujeta_con_iva_es_incoherente():
    assert ci.clasificar(_op(tipo_iva=D("21"), operacion="no_sujeta")).clasificacion is None


def test_servicio_emitido_a_empresa_extranjera_sin_iva_no_esta_sujeto():
    r = ci.clasificar(_op(tipo="emitida", tipo_iva=D(0), nif_contraparte=NIF_ALEMAN))
    assert r.clasificacion == "no_sujeta" and "69" in r.regla.articulo


def test_emitida_a_extranjero_con_iva_es_incoherente():
    r = ci.clasificar(_op(tipo="emitida", tipo_iva=D("21"), nif_contraparte=NIF_ALEMAN))
    assert r.clasificacion is None


# --- Validaciones y coherencia con el resto del núcleo ----------------------

def test_operacion_desconocida_se_rechaza():
    with pytest.raises(ValueError):
        _op(operacion="rara")
    with pytest.raises(ValueError):
        _op(tipo="otra")


def test_los_nombres_especiales_son_los_que_usa_pendientes():
    assert pe.CLASIFICACIONES_ESPECIALES == ci.ESPECIALES
    assert ci.ESPECIALES == {"exenta", "no_sujeta", "isp"}


# --- Casos propuestos (no validados) ----------------------------------------

def test_los_casos_propuestos_se_cumplen_con_el_codigo():
    import json
    from pathlib import Path

    ruta = Path(__file__).parents[2] / "docs" / "casos_propuestos" / "clasificacion_iva.json"
    casos = json.loads(ruta.read_text(encoding="utf-8"))["casos"]
    assert len(casos) >= 10
    for c in casos:
        e = dict(c["entrada"])
        e["fecha"] = date.fromisoformat(e["fecha"])
        e["tipo_iva"] = D(e["tipo_iva"])
        assert ci.clasificar(ci.Operacion(**e)).clasificacion == c["esperado"], c["situacion"]
