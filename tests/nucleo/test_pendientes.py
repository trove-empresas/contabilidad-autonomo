"""Pruebas de las reglas que dejan una factura pendiente (issue #10).
Solo facturas ficticias: NIF y nombres inventados."""

from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from contabilidad_autonomo import facturas as fa
from contabilidad_autonomo import pendientes as pe

# NIF ficticios con control válido (calculados con el algoritmo oficial).
NIF_DNI = "12345678Z"
NIF_NIE = "X1234567L"
NIF_CIF = "A58818501"  # A: control dígito
NIF_CIF_LETRA = "Q2826000H"  # Q: control letra


def _factura(**kw):
    base = dict(
        tipo=fa.RECIBIDA, emisor_nombre="Proveedor Ficticio SL",
        emisor_nif=NIF_CIF, receptor_nombre="Autónomo Ficticio",
        receptor_nif=NIF_DNI, fecha=date(2026, 2, 15), numero="F-001",
        total=D("121.00"), confianza_extraccion=D("0.95"),
        lineas=(fa.LineaIva(D("100.00"), D("21"), D("21.00")),),
        clasificacion_iva="general", confianza_clasificacion=D("0.95"),
    )
    base.update(kw)
    return fa.Factura(**base)


def test_factura_correcta_no_queda_pendiente():
    assert pe.motivos_pendiente(_factura()) == []
    assert not pe.esta_pendiente(_factura())


def test_confianza_justo_en_el_umbral_pasa_y_por_debajo_no():
    assert pe.motivos_pendiente(_factura(confianza_extraccion=D("0.90"))) == []
    m = pe.motivos_pendiente(_factura(confianza_extraccion=D("0.89")))
    assert len(m) == 1 and "umbral" in m[0]


def test_usa_la_confianza_mas_baja_de_extraccion_y_clasificacion():
    m = pe.motivos_pendiente(_factura(confianza_clasificacion=D("0.50")))
    assert len(m) == 1 and "0.50" in m[0]


def test_umbral_configurable():
    f = _factura(confianza_extraccion=D("0.95"))
    assert pe.motivos_pendiente(f, umbral=D("0.99"))
    assert pe.motivos_pendiente(f, umbral=D("0.80")) == []


def test_umbral_desde_entorno():
    assert pe.umbral_confianza({}) == D("0.90")
    assert pe.umbral_confianza({"UMBRAL_CONFIANZA": "0.75"}) == D("0.75")
    assert pe.umbral_confianza({"UMBRAL_CONFIANZA": " "}) == D("0.90")


@pytest.mark.parametrize("valor", ["abc", "1.5", "-0.1", "NaN"])
def test_umbral_invalido_es_error_no_se_ignora(valor):
    with pytest.raises(ValueError):
        pe.umbral_confianza({"UMBRAL_CONFIANZA": valor})


def test_importes_que_no_cuadran():
    m = pe.motivos_pendiente(_factura(total=D("125.00")))
    assert len(m) == 1 and "no cuadran" in m[0]


def test_margen_de_un_centimo_por_tipo_de_iva():
    una = _factura(total=D("121.01"))
    assert pe.motivos_pendiente(una) == []
    assert pe.motivos_pendiente(_factura(total=D("121.02")))  # 2 cént., 1 tipo
    dos = (fa.LineaIva(D("100.00"), D("21"), D("21.00")),
           fa.LineaIva(D("50.00"), D("10"), D("5.00")))
    assert pe.motivos_pendiente(_factura(lineas=dos, total=D("176.02"))) == []
    assert pe.motivos_pendiente(_factura(lineas=dos, total=D("176.03")))


def test_la_retencion_se_resta_en_el_cuadre():
    f = _factura(retencion_irpf=D("15.00"), total=D("106.00"))
    assert pe.motivos_pendiente(f) == []
    assert pe.motivos_pendiente(replace(f, total=D("121.00")))


@pytest.mark.parametrize("nif", [NIF_DNI, NIF_NIE, NIF_CIF, NIF_CIF_LETRA,
                                 "ES" + NIF_CIF, "DE123456789", "fr12345678901"])
def test_nif_validos(nif):
    assert pe.nif_valido(nif)


@pytest.mark.parametrize("nif", ["12345678A", "X1234567A", "A58818502",
                                 "Q2826000A", "1234", "ES12", "ñ"])
def test_nif_invalidos(nif):
    assert not pe.nif_valido(nif)


def test_nif_con_control_invalido_deja_pendiente_a_emisor_y_receptor():
    m = pe.motivos_pendiente(_factura(emisor_nif="A58818502"))
    assert any("emisor" in x for x in m)
    m = pe.motivos_pendiente(_factura(receptor_nif="12345678A"))
    assert any("receptor" in x for x in m)


@pytest.mark.parametrize("campo,valor", [
    ("emisor_nif", ""), ("receptor_nif", " "), ("numero", ""),
    ("lineas", ()), ("clasificacion_iva", None), ("clasificacion_iva", " "),
])
def test_campo_clave_ausente(campo, valor):
    m = pe.motivos_pendiente(_factura(**{campo: valor}))
    assert any(x.startswith("falta") for x in m)


def test_clasificacion_especial_de_contraparte_nueva_queda_pendiente():
    f = _factura(clasificacion_iva="isp")
    m = pe.motivos_pendiente(f)
    assert len(m) == 1 and "primera vez" in m[0]


def test_clasificacion_especial_de_contraparte_conocida_pasa():
    f = _factura(clasificacion_iva="isp")
    assert pe.motivos_pendiente(f, conocidas={(NIF_CIF, "isp")}) == []
    # otra clasificación o otro NIF no cuentan como conocidos
    assert pe.motivos_pendiente(f, conocidas={(NIF_CIF, "exenta")})
    assert pe.motivos_pendiente(f, conocidas={(NIF_CIF_LETRA, "isp")})


def test_en_emitidas_la_contraparte_es_el_receptor():
    f = _factura(tipo=fa.EMITIDA, emisor_nif=NIF_DNI, receptor_nif=NIF_CIF,
                 clasificacion_iva="exenta")
    assert pe.motivos_pendiente(f, conocidas={(NIF_CIF, "exenta")}) == []
    assert pe.motivos_pendiente(f, conocidas={(NIF_DNI, "exenta")})


def test_clasificaciones_conocidas_solo_cuenta_confirmadas(tmp_path):
    con = fa.abrir(tmp_path / "app.sqlite3")
    fa.crear(con, _factura(clasificacion_iva="isp", estado=fa.CONFIRMADA))
    fa.crear(con, _factura(clasificacion_iva="exenta", emisor_nif=NIF_CIF_LETRA))
    assert pe.clasificaciones_conocidas(con) == {(NIF_CIF, "isp")}
    con.close()


def test_varios_motivos_a_la_vez():
    m = pe.motivos_pendiente(_factura(
        confianza_extraccion=D("0.1"), total=D("999"), numero=""))
    assert len(m) == 3


def test_filtro_de_calculo_deja_fuera_las_pendientes():
    ok = _factura(estado=fa.CONFIRMADA, numero="1")
    pend = _factura(estado=fa.PENDIENTE, numero="2")
    assert pe.para_calculo([pend, ok]) == [ok]
    assert pe.para_calculo([pend]) == []


def test_la_confirmacion_del_usuario_manda_sobre_las_reglas():
    # Una factura con importes raros pero confirmada por el usuario entra.
    f = _factura(total=D("999.00"), estado=fa.CONFIRMADA)
    assert pe.para_calculo([f]) == [f]
