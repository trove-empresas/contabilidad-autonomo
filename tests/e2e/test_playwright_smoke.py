"""Prueba de wiring de Playwright: todavía no hay interfaz que probar (la app
no tiene código), así que esto solo confirma que el navegador headless
arranca y puede leer una página HTML. Cuando exista la interfaz real
(FastAPI + Jinja + htmx), estas pruebas navegarán contra ella en vez de
contra este HTML de ejemplo.
"""

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def test_el_navegador_headless_arranca_y_lee_una_pagina(page):
    ruta = (FIXTURES / "pagina_prueba.html").resolve()
    page.goto(f"file://{ruta}")

    assert page.locator("#saludo").inner_text() == "Hola, contabilidad-autonomo"
