"""Pruebas del esquema y repositorio de facturas (issue #9).
Solo facturas ficticias: NIF y nombres inventados."""

from datetime import date
from decimal import Decimal as D

import pytest

from contabilidad_autonomo import facturas as fa


def _factura(**kw):
    base = dict(
        tipo=fa.RECIBIDA, emisor_nombre="Proveedor Ficticio SL",
        emisor_nif="B00000000", receptor_nombre="Autónomo Ficticio",
        receptor_nif="00000000T", fecha=date(2026, 2, 15), numero="F-001",
        total=D("121.00"), confianza_extraccion=D("0.95"),
        lineas=(fa.LineaIva(D("100.00"), D("21"), D("21.00")),),
        concepto="Servicio ficticio",
    )
    base.update(kw)
    return fa.Factura(**base)


@pytest.fixture
def con(tmp_path):
    c = fa.abrir(tmp_path / "datos" / "app.sqlite3")
    yield c
    c.close()


def test_crear_y_leer_conserva_todo(con):
    f = fa.crear(con, _factura(
        retencion_irpf=D("15.00"), clasificacion_iva="general",
        confianza_clasificacion=D("0.88"), ruta_archivo="datos/f1.pdf"))
    assert f.id is not None
    assert fa.leer(con, f.id) == f


def test_leer_inexistente(con):
    assert fa.leer(con, 999) is None


def test_varias_lineas_por_tipo_de_iva(con):
    lineas = (fa.LineaIva(D("100.00"), D("21"), D("21.00")),
              fa.LineaIva(D("50.00"), D("10"), D("5.00")),
              fa.LineaIva(D("20.00"), D("4"), D("0.80")))
    f = fa.crear(con, _factura(lineas=lineas, total=D("196.80")))
    assert fa.leer(con, f.id).lineas == lineas


def test_sin_errores_de_redondeo(con):
    # 0,10 + 0,20 con float da 0.30000000000000004; aquí debe ser exacto.
    f = fa.crear(con, _factura(lineas=(
        fa.LineaIva(D("0.10"), D("21"), D("0.02")),
        fa.LineaIva(D("0.20"), D("21"), D("0.04"))), total=D("0.36")))
    leida = fa.leer(con, f.id)
    assert sum(l.base for l in leida.lineas) == D("0.30")
    assert isinstance(leida.total, D) and leida.total == D("0.36")
    tipos = {r[0] for r in con.execute(
        "SELECT typeof(total_cent) FROM facturas UNION "
        "SELECT typeof(base_cent) FROM lineas_iva")}
    assert tipos == {"integer"}


def test_importe_con_mas_de_dos_decimales_se_rechaza_y_no_deja_restos(con):
    with pytest.raises(ValueError):
        fa.crear(con, _factura(total=D("10.005")))
    assert fa.listar(con, 2026) == []


def test_rechaza_float(con):
    with pytest.raises(TypeError):
        fa.crear(con, _factura(total=10.5))


def test_linea_invalida_deshace_la_factura(con):
    mala = (fa.LineaIva(D("1.001"), D("21"), D("0.21")),)
    with pytest.raises(ValueError):
        fa.crear(con, _factura(lineas=mala))
    assert con.execute("SELECT COUNT(*) FROM facturas").fetchone()[0] == 0


@pytest.mark.parametrize("kw", [
    {"tipo": "otra"}, {"estado": "rara"},
    {"confianza_extraccion": D("1.5")}, {"confianza_clasificacion": D("-0.1")}])
def test_validaciones(con, kw):
    with pytest.raises(ValueError):
        fa.crear(con, _factura(**kw))


def test_listar_por_trimestre_y_anio(con):
    fechas = [date(2026, 1, 1), date(2026, 3, 31), date(2026, 4, 1),
              date(2026, 12, 31), date(2027, 1, 1), date(2025, 12, 31)]
    for i, d in enumerate(fechas):
        fa.crear(con, _factura(fecha=d, numero=f"N{i}"))
    nums = lambda l: [f.numero for f in l]
    assert nums(fa.listar(con, 2026, 1)) == ["N0", "N1"]
    assert nums(fa.listar(con, 2026, 2)) == ["N2"]
    assert nums(fa.listar(con, 2026, 4)) == ["N3"]
    assert nums(fa.listar(con, 2026)) == ["N0", "N1", "N2", "N3"]
    with pytest.raises(ValueError):
        fa.listar(con, 2026, 5)


def test_listar_por_estado_y_cambiar_estado(con):
    a = fa.crear(con, _factura(numero="A"))
    fa.crear(con, _factura(numero="B"))
    assert a.estado == fa.PENDIENTE
    fa.cambiar_estado(con, a.id, fa.CONFIRMADA)
    assert fa.leer(con, a.id).estado == fa.CONFIRMADA
    assert [f.numero for f in fa.listar(con, 2026, estado=fa.CONFIRMADA)] == ["A"]
    assert [f.numero for f in fa.listar(con, 2026, estado=fa.PENDIENTE)] == ["B"]
    with pytest.raises(ValueError):
        fa.cambiar_estado(con, a.id, "rara")
    with pytest.raises(KeyError):
        fa.cambiar_estado(con, 999, fa.CONFIRMADA)


def test_emitida_y_recibida(con):
    e = fa.crear(con, _factura(tipo=fa.EMITIDA, numero="E1"))
    assert fa.leer(con, e.id).tipo == fa.EMITIDA


def test_migraciones_con_version_e_idempotentes(tmp_path):
    ruta = tmp_path / "x.sqlite3"
    c = fa.abrir(ruta)
    assert c.execute("PRAGMA user_version").fetchone()[0] == fa.VERSION_ESQUEMA
    fa.crear(c, _factura())
    c.close()
    c2 = fa.abrir(ruta)  # reabrir no pierde datos ni repite migraciones
    assert len(fa.listar(c2, 2026)) == 1
    c2.close()


def test_base_de_version_futura_no_se_toca(tmp_path):
    ruta = tmp_path / "x.sqlite3"
    c = fa.abrir(ruta)
    c.execute(f"PRAGMA user_version = {fa.VERSION_ESQUEMA + 1}")
    c.close()
    with pytest.raises(RuntimeError):
        fa.abrir(ruta)
