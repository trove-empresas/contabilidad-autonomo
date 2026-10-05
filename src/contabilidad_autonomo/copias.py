"""Copia de seguridad local de la base de datos SQLite.

Decisión 2026-09-24 (docs/decisiones.md): copia en caliente con la API de
SQLite, nombre ``AAAA-MM-DD_HHMMSS.sqlite3``, una al día como máximo al
arrancar, otra antes de operaciones en bloque, y **nunca se borra nada**:
si las copias ocupan demasiado, solo se avisa.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_MARCA_ARRANQUE = ".ultimo_arranque"


def copiar_base(
    base: Path,
    carpeta_copias: Path,
    ahora: datetime | None = None,
    motivo: str = "operacion",
) -> Path:
    """Copia ``base`` en ``carpeta_copias`` y devuelve la ruta de la copia.

    ``motivo`` solo se usa internamente (``"arranque"`` actualiza la marca del
    límite diario); no cambia el nombre del archivo.
    """
    ahora = ahora or datetime.now()
    carpeta_copias = Path(carpeta_copias)
    carpeta_copias.mkdir(parents=True, exist_ok=True)
    destino = carpeta_copias / f"{ahora:%Y-%m-%d_%H%M%S}.sqlite3"
    if destino.exists():
        raise FileExistsError(f"Ya existe la copia {destino.name}; no se sobrescribe.")

    origen = sqlite3.connect(base)
    copia = sqlite3.connect(destino)
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()

    if motivo == "arranque":
        (carpeta_copias / _MARCA_ARRANQUE).write_text(f"{ahora:%Y-%m-%d}\n")
    return destino


def copia_al_arrancar(
    base: Path, carpeta_copias: Path, ahora: datetime | None = None
) -> Path | None:
    """Hace la copia de arranque, como mucho una al día. ``None`` si ya hay."""
    ahora = ahora or datetime.now()
    marca = Path(carpeta_copias) / _MARCA_ARRANQUE
    if marca.exists() and marca.read_text().strip() == ahora.date().isoformat():
        return None
    return copiar_base(base, carpeta_copias, ahora=ahora, motivo="arranque")


def copias_ocupan_mas_de(carpeta_copias: Path, limite_bytes: int) -> bool:
    """Indica si las copias superan ``limite_bytes`` (solo avisa, no borra)."""
    carpeta_copias = Path(carpeta_copias)
    if not carpeta_copias.exists():
        return False
    total = sum(f.stat().st_size for f in carpeta_copias.glob("*.sqlite3"))
    return total > limite_bytes
