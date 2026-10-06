"""Pruebas de las rutas protegidas propias de contabilidad-autonomo."""
import pathlib
import unittest

from comprobar_fusion import cargar_lineas, es_protegida, patrones_mal_escritos

RUTAS = cargar_lineas((pathlib.Path(__file__).parent.parent / "rutas-protegidas.txt").read_text(encoding="utf-8"))


class RutasProyecto(unittest.TestCase):
    def test_ninguna_ruta_mal_escrita(self):
        self.assertEqual(patrones_mal_escritos(RUTAS), [])

    def test_protegidas(self):
        for r in [
            # generales
            "CLAUDE.md", ".github/workflows/ci.yml", ".github/rutas-protegidas.txt",
            "casos_validados/README.md", ".env", ".env.example",
            # reglas y cálculos fiscales
            "src/contabilidad_autonomo/fiscal/tipos.py", "src/contabilidad_autonomo/iva.py",
            "src/contabilidad_autonomo/irpf.py", "src/contabilidad_autonomo/modelo_303.py",
            "src/contabilidad_autonomo/modelos/m130.py", "src/contabilidad_autonomo/reglas_fiscales.py",
            "tests/nucleo/fiscal/test_iva.py",
            # datos
            "src/contabilidad_autonomo/facturas.py", "src/contabilidad_autonomo/copias.py",
            "src/contabilidad_autonomo/migraciones/0002.sql",
            # seguridad
            "pyproject.toml", ".gitignore",
        ]:
            self.assertTrue(es_protegida(r, RUTAS), r)

    def test_no_protegidas(self):
        for r in [
            "README.md", "docs/producto.md", "docs/decisiones.md",
            "src/contabilidad_autonomo/__init__.py", "src/contabilidad_autonomo/web/plantillas/inicio.html",
            "tests/nucleo/test_paquete.py", "tests/e2e/test_playwright_smoke.py",
        ]:
            self.assertFalse(es_protegida(r, RUTAS), r)


if __name__ == "__main__":
    unittest.main()
