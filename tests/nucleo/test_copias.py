"""Pruebas de la copia de seguridad (decisión 2026-09-24 en docs/decisiones.md).
Solo usan bases ficticias en directorios temporales."""

import sqlite3
from datetime import datetime

from contabilidad_autonomo.copias import (
    copia_al_arrancar,
    copiar_base,
    copias_ocupan_mas_de,
)


def _crear_base(ruta):
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE t (x TEXT)")
    con.execute("INSERT INTO t VALUES ('ficticio')")
    con.commit()
    con.close()


def _leer(ruta):
    con = sqlite3.connect(ruta)
    try:
        return con.execute("SELECT x FROM t").fetchall()
    finally:
        con.close()


def test_copia_legible_con_nombre_de_fecha_y_hora(tmp_path):
    base = tmp_path / "app.sqlite3"
    _crear_base(base)
    destino = copiar_base(base, tmp_path / "copias", ahora=datetime(2026, 10, 5, 8, 30, 15))
    assert destino.name == "2026-10-05_083015.sqlite3"
    assert _leer(destino) == [("ficticio",)]


def test_copia_con_la_base_abierta_y_en_uso(tmp_path):
    base = tmp_path / "app.sqlite3"
    _crear_base(base)
    abierta = sqlite3.connect(base)
    abierta.execute("INSERT INTO t VALUES ('otra')")
    abierta.commit()
    destino = copiar_base(base, tmp_path / "copias")
    abierta.close()
    assert len(_leer(destino)) == 2


def test_al_arrancar_solo_una_copia_al_dia(tmp_path):
    base = tmp_path / "app.sqlite3"
    _crear_base(base)
    copias = tmp_path / "copias"
    primera = copia_al_arrancar(base, copias, ahora=datetime(2026, 10, 5, 8, 0, 0))
    segunda = copia_al_arrancar(base, copias, ahora=datetime(2026, 10, 5, 20, 0, 0))
    siguiente_dia = copia_al_arrancar(base, copias, ahora=datetime(2026, 10, 6, 8, 0, 0))
    assert primera is not None and segunda is None and siguiente_dia is not None
    assert len(list(copias.glob("*.sqlite3"))) == 2


def test_una_copia_previa_a_operacion_no_cuenta_para_el_limite_de_arranque(tmp_path):
    base = tmp_path / "app.sqlite3"
    _crear_base(base)
    copias = tmp_path / "copias"
    copiar_base(base, copias, ahora=datetime(2026, 10, 5, 7, 0, 0), motivo="operacion")
    assert copia_al_arrancar(base, copias, ahora=datetime(2026, 10, 5, 8, 0, 0)) is not None


def test_nunca_borra_copias_existentes(tmp_path):
    base = tmp_path / "app.sqlite3"
    _crear_base(base)
    copias = tmp_path / "copias"
    copias.mkdir()
    antigua = copias / "2020-01-01_000000.sqlite3"
    antigua.write_bytes(b"antigua")
    copiar_base(base, copias, ahora=datetime(2026, 10, 5, 8, 0, 0))
    copia_al_arrancar(base, copias, ahora=datetime(2026, 10, 5, 9, 0, 0))
    assert antigua.read_bytes() == b"antigua"


def test_avisa_si_las_copias_ocupan_mas_del_limite(tmp_path):
    copias = tmp_path / "copias"
    copias.mkdir()
    (copias / "a.sqlite3").write_bytes(b"x" * 1000)
    assert copias_ocupan_mas_de(copias, 500) is True
    assert copias_ocupan_mas_de(copias, 5000) is False
    assert copias_ocupan_mas_de(tmp_path / "no_existe", 1) is False


def test_no_sobrescribe_una_copia_con_el_mismo_nombre(tmp_path):
    base = tmp_path / "app.sqlite3"
    _crear_base(base)
    copias = tmp_path / "copias"
    momento = datetime(2026, 10, 5, 8, 0, 0)
    copiar_base(base, copias, ahora=momento)
    import pytest

    with pytest.raises(FileExistsError):
        copiar_base(base, copias, ahora=momento)
