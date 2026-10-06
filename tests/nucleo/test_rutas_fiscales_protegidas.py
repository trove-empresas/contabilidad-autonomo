"""Todo archivo que cite normativa fiscal debe ser ruta protegida (issue #23).

El principio 4 del CLAUDE.md obliga a que cada regla fiscal lleve su
referencia normativa. Esta prueba busca esas referencias en el código, las
pruebas y los casos, y falla si algún archivo que las tiene no está en
`.github/rutas-protegidas.txt`. Así, un archivo fiscal nuevo con un nombre
que no encaje en ningún patrón no puede fusionarse solo: el CI sale en rojo.

Este archivo también es ruta protegida (su nombre contiene «fiscal»).
"""

import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / ".github" / "scripts"))

from comprobar_fusion import cargar_lineas, es_protegida  # noqa: E402

RUTAS = cargar_lineas((RAIZ / ".github" / "rutas-protegidas.txt").read_text(encoding="utf-8"))

# Referencias normativas fiscales: leyes y reales decretos con número, sus
# siglas, artículos, identificadores del BOE y modelos de la AEAT.
REFERENCIA = re.compile(
    r"\bLey\s+\d+/\d{4}"
    r"|\b(?:Real\s+Decreto|RD)\s+\d+/\d{4}"
    r"|\b(?:LIVA|RIVA|LIRPF|RIRPF|LGT)\b"
    r"|\bart(?:ículo|\.)s?\s*\d+"
    r"|\bBOE-A-\d{4}-\d+"
    r"|\bmodelos?\s*(?:303|130|390|347|100|111|190)\b",
    re.IGNORECASE,
)

CARPETAS = ["src", "tests", "docs", "casos_validados"]
EXTENSIONES = {".py", ".json", ".sql", ".toml", ".yaml", ".yml", ".csv"}


def archivos_con_referencias():
    for carpeta in CARPETAS:
        for ruta in sorted((RAIZ / carpeta).rglob("*")):
            if ruta.is_file() and ruta.suffix.lower() in EXTENSIONES:
                if REFERENCIA.search(ruta.read_text(encoding="utf-8", errors="replace")):
                    yield ruta.relative_to(RAIZ).as_posix()


def test_detecta_referencias_normativas():
    for texto in ["art. 20 LIVA", "artículo 84.Uno.2.º", "Ley 37/1992", "RD 439/2007",
                  "BOE-A-1992-28740", "modelo 303", "Modelos 130"]:
        assert REFERENCIA.search(texto), texto
    for texto in ["IVA del 21 %", "partícula", "modelo de datos", "arte 5"]:
        assert not REFERENCIA.search(texto), texto


def test_hay_archivos_fiscales_que_comprobar():
    assert "src/contabilidad_autonomo/clasificacion_iva.py" in list(archivos_con_referencias())


def test_todo_archivo_con_referencias_normativas_esta_protegido():
    sin_proteger = [r for r in archivos_con_referencias() if not es_protegida(r, RUTAS)]
    assert not sin_proteger, (
        "Estos archivos citan normativa fiscal y no son ruta protegida; añádelos a "
        ".github/rutas-protegidas.txt: " + ", ".join(sin_proteger)
    )
