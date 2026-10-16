"""Pruebas de la persistencia de la afectación y datos de deducción (issue #27).
Solo bases y facturas ficticias: NIF y nombres inventados."""

import sqlite3
from datetime import date
from decimal import Decimal as D

import pytest

from contabilidad_autonomo import deducciones as de
from contabilidad_autonomo import facturas as fa
from contabilidad_autonomo import modelo_303 as m

TITULAR = "00000000T"


def _factura(**kw):
    base = dict(
        tipo=fa.RECIBIDA, emisor_nombre="Proveedor Ficticio SL",
        emisor_nif="B00000000", receptor_nombre="Autónomo Ficticio",
        receptor_nif=TITULAR, fecha=date(2026, 2, 15), numero="F-001",
        total=D("121.00"), confianza_extraccion=D("0.95"),
        lineas=(fa.LineaIva(D("100.00"), D("21"), D("21.00")),),
        clasificacion_iva="general", estado=fa.CONFIRMADA)
    base.update(kw)
    return fa.Factura(**base)


@pytest.fixture
def con(tmp_path):
    c = fa.abrir(tmp_path / "app.sqlite3")
    yield c
    c.close()


def test_guardar_y_leer_todo(con):
    f = fa.crear(con, _factura())
    datos = m.DatosDeduccion(
        m.AFECTACION_VEHICULO, simplificada=True, tipo_isp=D("10"),
        fecha_recepcion=date(2026, 3, 1), deducir_en=(2026, 3))
    de.guardar(con, f.id, datos, fecha_devengo=date(2026, 2, 20))
    g = de.leer(con, f.id)
    assert g.datos == datos
    assert g.fecha_devengo == date(2026, 2, 20)


def test_campos_opcionales_vuelven_a_none(con):
    f = fa.crear(con, _factura())
    de.guardar(con, f.id, m.DatosDeduccion(m.AFECTACION_TOTAL))
    g = de.leer(con, f.id)
    assert g.datos == m.DatosDeduccion(m.AFECTACION_TOTAL)
    assert g.fecha_devengo is None


def test_sin_datos_guardados_leer_da_none(con):
    f = fa.crear(con, _factura())
    assert de.leer(con, f.id) is None


def test_guardar_dos_veces_reemplaza(con):
    f = fa.crear(con, _factura())
    de.guardar(con, f.id, m.DatosDeduccion(m.AFECTACION_TOTAL))
    de.guardar(con, f.id, m.DatosDeduccion(m.AFECTACION_NINGUNA))
    assert de.leer(con, f.id).datos.afectacion == m.AFECTACION_NINGUNA
    assert con.execute("SELECT COUNT(*) FROM datos_deduccion").fetchone()[0] == 1


def test_factura_inexistente_o_emitida_se_rechaza(con):
    with pytest.raises(KeyError):
        de.guardar(con, 99, m.DatosDeduccion(m.AFECTACION_TOTAL))
    e = fa.crear(con, _factura(tipo=fa.EMITIDA))
    with pytest.raises(ValueError):
        de.guardar(con, e.id, m.DatosDeduccion(m.AFECTACION_TOTAL))


def test_la_base_rechaza_afectacion_invalida(con):
    f = fa.crear(con, _factura())
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO datos_deduccion (factura_id, afectacion)"
                    " VALUES (?, 'inventada')", (f.id,))


def test_borrar_factura_borra_sus_datos(con):
    f = fa.crear(con, _factura())
    de.guardar(con, f.id, m.DatosDeduccion(m.AFECTACION_TOTAL))
    con.execute("DELETE FROM facturas WHERE id = ?", (f.id,))
    assert con.execute("SELECT COUNT(*) FROM datos_deduccion").fetchone()[0] == 0


def test_borrar_datos_deja_la_factura_pendiente_en_el_303(con):
    f = fa.crear(con, _factura())
    de.guardar(con, f.id, m.DatosDeduccion(m.AFECTACION_TOTAL))
    de.borrar(con, f.id)
    r = de.calcular_303_guardado(con, 2026, 1, TITULAR)
    assert [p.factura_id for p in r.pendientes] == [f.id]


def test_migracion_desde_v1_conserva_los_datos(tmp_path):
    ruta = tmp_path / "vieja.sqlite3"
    c = sqlite3.connect(ruta)
    c.execute("PRAGMA foreign_keys = ON")
    c.executescript("BEGIN;" + fa._MIGRACIONES[0])  # esquema v1 tal cual
    c.execute("PRAGMA user_version = 1")
    c.execute(
        "INSERT INTO facturas (tipo, emisor_nombre, emisor_nif, receptor_nombre,"
        " receptor_nif, fecha, numero, total_cent, confianza_extraccion, estado)"
        " VALUES ('recibida','P','B00000000','A','00000000T','2026-02-15','F-1',"
        "12100,'0.95','confirmada')")
    c.execute("INSERT INTO lineas_iva (factura_id, base_cent, tipo_iva, cuota_cent)"
              " VALUES (1, 10000, '21', 2100)")
    c.commit()
    c.close()
    con = fa.abrir(ruta)
    assert con.execute("PRAGMA user_version").fetchone()[0] == fa.VERSION_ESQUEMA >= 2
    f = fa.leer(con, 1)
    assert f.total == D("121.00") and f.lineas[0].cuota == D("21.00")
    assert de.leer(con, 1) is None  # sigue sin afectación: pendiente
    con.close()


def test_calculo_303_a_partir_de_lo_guardado(con):
    emitida = fa.crear(con, _factura(
        tipo=fa.EMITIDA, receptor_nif="X0000000X", emisor_nif=TITULAR,
        numero="E-1", lineas=(fa.LineaIva(D("1000.00"), D("21"), D("210.00")),),
        total=D("1210.00")))
    total = fa.crear(con, _factura(numero="R-1"))
    coche = fa.crear(con, _factura(
        numero="R-2", lineas=(fa.LineaIva(D("200.00"), D("21"), D("42.00")),),
        total=D("242.00")))
    sin_datos = fa.crear(con, _factura(numero="R-3"))
    de.guardar(con, total.id, m.DatosDeduccion(m.AFECTACION_TOTAL))
    de.guardar(con, coche.id, m.DatosDeduccion(m.AFECTACION_VEHICULO))
    r = de.calcular_303_guardado(con, 2026, 1, TITULAR)
    assert r.total_devengado == D("210.00")
    assert r.total_deducible == D("21.00") + D("21.00")  # 100 % + 50 % de 42
    assert r.resultado == D("168.00")
    assert set(r.facturas_incluidas) == {emitida.id, total.id, coche.id}
    assert [p.factura_id for p in r.pendientes] == [sin_datos.id]


def test_devengo_corregido_y_trimestre_elegido_se_aplican(con):
    # Factura de febrero (T1) con devengo corregido a abril: cuenta en T2.
    a = fa.crear(con, _factura(numero="R-1"))
    de.guardar(con, a.id, m.DatosDeduccion(m.AFECTACION_TOTAL),
               fecha_devengo=date(2026, 4, 2))
    # Recibida en T1 pero el usuario elige deducirla en T3.
    b = fa.crear(con, _factura(numero="R-2"))
    de.guardar(con, b.id, m.DatosDeduccion(m.AFECTACION_TOTAL, deducir_en=(2026, 3)))
    t1 = de.calcular_303_guardado(con, 2026, 1, TITULAR)
    t2 = de.calcular_303_guardado(con, 2026, 2, TITULAR)
    t3 = de.calcular_303_guardado(con, 2026, 3, TITULAR)
    assert t1.facturas_incluidas == ()
    assert t2.facturas_incluidas == (a.id,)
    assert t3.facturas_incluidas == (b.id,) and t3.de_periodos_anteriores == (b.id,)


def test_tipo_isp_guardado_se_usa(con):
    f = fa.crear(con, _factura(
        clasificacion_iva="isp", emisor_nif="XX0000000",
        lineas=(fa.LineaIva(D("100.00"), D("0"), D("0.00")),), total=D("100.00")))
    de.guardar(con, f.id, m.DatosDeduccion(m.AFECTACION_TOTAL, tipo_isp=D("10")))
    r = de.calcular_303_guardado(con, 2026, 1, TITULAR)
    assert r.cuota_isp == D("10.00") and r.total_deducible == D("10.00")


def test_resultado_igual_a_pasar_los_datos_en_memoria(con):
    f = fa.crear(con, _factura())
    datos = m.DatosDeduccion(m.AFECTACION_VEHICULO)
    de.guardar(con, f.id, datos)
    en_memoria = m.calcular_303([fa.leer(con, f.id)], 2026, 1, TITULAR,
                                deducciones={f.id: datos})
    assert de.calcular_303_guardado(con, 2026, 1, TITULAR) == en_memoria
