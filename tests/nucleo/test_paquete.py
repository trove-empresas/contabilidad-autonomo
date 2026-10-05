"""Prueba de wiring: confirma que el paquete se instala y se puede importar
antes de que exista ningún cálculo fiscal real."""

from contabilidad_autonomo import __version__


def test_el_paquete_se_importa_y_tiene_version():
    assert __version__ == "0.1.0"
