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
    assert r.clasificacion is None and "extranjero" in r.motivo


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
    # Sin constar que es empresario, no se clasifica (ver pruebas de abajo).
    assert r.clasificacion is None
    r = ci.clasificar(_op(tipo="emitida", tipo_iva=D(0), nif_contraparte=NIF_ALEMAN,
                          contraparte_empresario=True))
    assert r.clasificacion == "no_sujeta_loc_ue" and "69" in r.regla.articulo


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
    assert ci.ESPECIALES == {"exenta", "no_sujeta", "isp",
                             "no_sujeta_loc_ue", "no_sujeta_loc_no_ue"}


# --- Casos propuestos (no validados) ----------------------------------------

def test_los_casos_propuestos_se_cumplen_con_el_codigo():
    import json
    from pathlib import Path

    ruta = Path(__file__).parents[2] / "docs" / "casos_propuestos" / "clasificacion_iva.json"
    casos = json.loads(ruta.read_text(encoding="utf-8"))["casos"]
    assert len(casos) >= 15
    for c in casos:
        e = dict(c["entrada"])
        e["fecha"] = date.fromisoformat(e["fecha"])
        e["tipo_iva"] = D(e["tipo_iva"])
        r = ci.clasificar(ci.Operacion(**e))
        assert r.clasificacion == c["esperado"], c["situacion"]
        if "motivo_contiene" in c:
            assert c["motivo_contiene"] in r.motivo, c["situacion"]


# --- Revisión de Gonzalo en la PR #19 ---------------------------------------

def _emitida(**kw):
    base = dict(tipo="emitida", tipo_iva=D(0), contraparte_empresario=True)
    base.update(kw)
    return _op(**base)


def test_no_sujeta_por_localizacion_separa_ue_de_fuera_de_la_ue():
    ue = ci.clasificar(_emitida(nif_contraparte=NIF_ALEMAN))
    fuera = ci.clasificar(_emitida(nif_contraparte="", pais_contraparte="US"))
    assert ue.clasificacion == "no_sujeta_loc_ue" and "349" in ue.motivo
    assert fuera.clasificacion == "no_sujeta_loc_no_ue" and "349" not in fuera.motivo
    # "no_sujeta" queda solo para el art. 7.
    assert ci.clasificar(_op(tipo_iva=D(0), operacion="no_sujeta")).clasificacion == "no_sujeta"
    assert {"no_sujeta_loc_ue", "no_sujeta_loc_no_ue"} <= ci.ESPECIALES


def test_grecia_con_prefijo_el_cuenta_como_ue():
    r = ci.clasificar(_emitida(nif_contraparte="EL123456789"))
    assert r.clasificacion == "no_sujeta_loc_ue"


@pytest.mark.parametrize("empresario", [None, False])
def test_servicio_a_extranjero_sin_constar_empresario_es_indeterminado(empresario):
    r = ci.clasificar(_emitida(nif_contraparte=NIF_ALEMAN, contraparte_empresario=empresario))
    assert r.clasificacion is None and "empresario" in r.motivo


def test_iva_extranjero_en_factura_recibida_no_se_llama_iva_espanol():
    r = ci.clasificar(_op(tipo_iva=D("19"), nif_contraparte=NIF_ALEMAN, iva_pais="DE"))
    assert r.clasificacion is None
    assert "IVA extranjero" in r.motivo and "no deducible" in r.motivo
    assert "IVA español" not in r.motivo


def test_iva_espanol_cobrado_por_proveedor_extranjero():
    r = ci.clasificar(_op(tipo_iva=D("21"), nif_contraparte="IE1234567X", iva_pais="ES"))
    assert r.clasificacion is None
    assert "IVA español cobrado por proveedor extranjero" in r.motivo


def test_iva_de_proveedor_extranjero_sin_pais_de_iva_no_afirma_ninguno():
    r = ci.clasificar(_op(tipo_iva=D("21"), nif_contraparte=NIF_ALEMAN))
    assert r.clasificacion is None
    assert "IVA extranjero" in r.motivo and "IVA español" in r.motivo  # ambas opciones


@pytest.mark.parametrize("nif, esperado", [
    ("12345678Z", "ES"),            # DNI con letra correcta
    ("ES12345678Z", "ES"),
    ("X1234567L", "ES"),            # NIE con letra correcta
    ("A58818501", "ES"),            # CIF con dígito correcto
    ("12345678A", None),            # letra de control incorrecta
    ("123456789", None),            # EIN de EE. UU. sin prefijo: antes daba ES
    ("12-3456789", None),
    ("ES123456789", None),          # prefijo ES pero sin control válido
    ("", None),
    ("???", None),
    ("DE123456789", "DE"),
    ("EL123456789", "GR"),
])
def test_pais_de_solo_concluye_es_con_nif_espanol_valido(nif, esperado):
    assert ci.pais_de(nif) == esperado


def test_pais_explicito_prevalece():
    assert ci.pais_de("12345678Z", "fr") == "FR"


def test_proveedor_con_ein_sin_prefijo_queda_indeterminado_con_o_sin_iva():
    for tipo in (D(0), D("21")):
        r = ci.clasificar(_op(tipo_iva=tipo, nif_contraparte="123456789"))
        assert r.clasificacion is None and "contraparte" in r.motivo


def test_sin_nif_con_iva_sigue_clasificando_por_el_tipo():
    # Factura simplificada sin NIF: comportamiento anterior, sin cambios.
    assert ci.clasificar(_op(tipo="emitida", nif_contraparte="")).clasificacion == "general"


def test_las_reglas_citan_su_contraste_con_el_boe():
    assert ci.FECHA_CONTRASTE == date(2026, 10, 5)
    for r in ci.REGLAS.values():
        assert "BOE" in r.descripcion or "contrast" in r.descripcion, r.id
