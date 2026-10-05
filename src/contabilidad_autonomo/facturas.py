"""Esquema SQLite y repositorio mínimo de facturas (v1, issue #9).

Reglas de este módulo:

* Los importes viven como ``decimal.Decimal`` en Python y como **céntimos
  enteros** en la base de datos: nunca ``float``. Un importe con más de dos
  decimales se rechaza en vez de redondearse en silencio.
* Aquí no se calcula nada fiscal: solo se guarda y se lee. La clasificación
  y la confianza llegan ya decididas (la IA extrae, el código calcula).
* El esquema se versiona con ``PRAGMA user_version`` y migraciones en orden.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

EMITIDA = "emitida"
RECIBIDA = "recibida"
PENDIENTE = "pendiente"
CONFIRMADA = "confirmada"
_TIPOS = (EMITIDA, RECIBIDA)
_ESTADOS = (PENDIENTE, CONFIRMADA)

# Cada elemento es una migración; la posición + 1 es la versión que deja.
_MIGRACIONES = [
    """
    CREATE TABLE facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL CHECK (tipo IN ('emitida', 'recibida')),
        emisor_nombre TEXT NOT NULL,
        emisor_nif TEXT NOT NULL,
        receptor_nombre TEXT NOT NULL,
        receptor_nif TEXT NOT NULL,
        fecha TEXT NOT NULL,
        numero TEXT NOT NULL,
        retencion_irpf_cent INTEGER NOT NULL DEFAULT 0,
        total_cent INTEGER NOT NULL,
        concepto TEXT NOT NULL DEFAULT '',
        clasificacion_iva TEXT,
        confianza_extraccion TEXT NOT NULL,
        confianza_clasificacion TEXT,
        estado TEXT NOT NULL DEFAULT 'pendiente'
            CHECK (estado IN ('pendiente', 'confirmada')),
        ruta_archivo TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE lineas_iva (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        factura_id INTEGER NOT NULL REFERENCES facturas(id) ON DELETE CASCADE,
        base_cent INTEGER NOT NULL,
        tipo_iva TEXT NOT NULL,
        cuota_cent INTEGER NOT NULL
    );
    CREATE INDEX idx_facturas_fecha ON facturas(fecha);
    """,
]
VERSION_ESQUEMA = len(_MIGRACIONES)


def a_centimos(importe: Decimal) -> int:
    """Convierte un importe a céntimos enteros; falla si no es exacto."""
    if not isinstance(importe, Decimal):
        raise TypeError("Los importes deben ser Decimal, no float ni str.")
    if not importe.is_finite():
        raise ValueError("Importe no finito.")
    cent = importe * 100
    if cent != cent.to_integral_value():
        raise ValueError(f"El importe {importe} tiene más de dos decimales.")
    return int(cent)


def de_centimos(cent: int) -> Decimal:
    return Decimal(cent) / 100


@dataclass(frozen=True)
class LineaIva:
    base: Decimal
    tipo_iva: Decimal  # porcentaje, p. ej. Decimal("21")
    cuota: Decimal


@dataclass(frozen=True)
class Factura:
    tipo: str
    emisor_nombre: str
    emisor_nif: str
    receptor_nombre: str
    receptor_nif: str
    fecha: date
    numero: str
    total: Decimal
    confianza_extraccion: Decimal
    lineas: tuple[LineaIva, ...] = field(default_factory=tuple)
    retencion_irpf: Decimal = Decimal("0")
    concepto: str = ""
    clasificacion_iva: str | None = None
    confianza_clasificacion: Decimal | None = None
    estado: str = PENDIENTE
    ruta_archivo: str = ""
    id: int | None = None


def abrir(base: Path | str) -> sqlite3.Connection:
    """Abre (o crea) la base y la deja en la última versión del esquema."""
    if str(base) != ":memory:":
        Path(base).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(base)
    con.execute("PRAGMA foreign_keys = ON")
    migrar(con)
    return con


def migrar(con: sqlite3.Connection) -> None:
    actual = con.execute("PRAGMA user_version").fetchone()[0]
    if actual > VERSION_ESQUEMA:
        raise RuntimeError(
            f"La base es de una versión más nueva ({actual}) que esta app "
            f"({VERSION_ESQUEMA}); no se toca."
        )
    for version in range(actual, VERSION_ESQUEMA):
        # executescript confirma lo pendiente; la versión se fija justo después.
        con.executescript("BEGIN;" + _MIGRACIONES[version])
        con.execute(f"PRAGMA user_version = {version + 1}")
        con.commit()


def _dec(texto: str | None) -> Decimal | None:
    return None if texto is None else Decimal(texto)


def _validar(f: Factura) -> None:
    if f.tipo not in _TIPOS:
        raise ValueError(f"Tipo de factura desconocido: {f.tipo!r}")
    if f.estado not in _ESTADOS:
        raise ValueError(f"Estado desconocido: {f.estado!r}")
    for c in (f.confianza_extraccion, f.confianza_clasificacion):
        if c is not None and not (Decimal(0) <= c <= Decimal(1)):
            raise ValueError("La confianza debe estar entre 0 y 1.")


def crear(con: sqlite3.Connection, f: Factura) -> Factura:
    _validar(f)
    try:
        cur = con.execute(
            """INSERT INTO facturas (tipo, emisor_nombre, emisor_nif,
                receptor_nombre, receptor_nif, fecha, numero, retencion_irpf_cent,
                total_cent, concepto, clasificacion_iva, confianza_extraccion,
                confianza_clasificacion, estado, ruta_archivo)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f.tipo, f.emisor_nombre, f.emisor_nif, f.receptor_nombre,
             f.receptor_nif, f.fecha.isoformat(), f.numero,
             a_centimos(f.retencion_irpf), a_centimos(f.total), f.concepto,
             f.clasificacion_iva, str(f.confianza_extraccion),
             None if f.confianza_clasificacion is None
             else str(f.confianza_clasificacion),
             f.estado, f.ruta_archivo),
        )
        fid = cur.lastrowid
        con.executemany(
            "INSERT INTO lineas_iva (factura_id, base_cent, tipo_iva, cuota_cent)"
            " VALUES (?,?,?,?)",
            [(fid, a_centimos(l.base), str(l.tipo_iva), a_centimos(l.cuota))
             for l in f.lineas],
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    return replace(f, id=fid)


def _desde_fila(con: sqlite3.Connection, fila: tuple) -> Factura:
    (id_, tipo, en, eni, rn, rni, fecha, numero, ret, total, concepto, clas,
     conf_e, conf_c, estado, ruta) = fila
    lineas = tuple(
        LineaIva(de_centimos(b), Decimal(t), de_centimos(c))
        for b, t, c in con.execute(
            "SELECT base_cent, tipo_iva, cuota_cent FROM lineas_iva"
            " WHERE factura_id = ? ORDER BY id", (id_,))
    )
    return Factura(tipo, en, eni, rn, rni, date.fromisoformat(fecha), numero,
                   de_centimos(total), Decimal(conf_e), lineas,
                   de_centimos(ret), concepto, clas, _dec(conf_c), estado,
                   ruta, id_)


_COLUMNAS = ("id, tipo, emisor_nombre, emisor_nif, receptor_nombre, receptor_nif,"
             " fecha, numero, retencion_irpf_cent, total_cent, concepto,"
             " clasificacion_iva, confianza_extraccion, confianza_clasificacion,"
             " estado, ruta_archivo")


def leer(con: sqlite3.Connection, id_: int) -> Factura | None:
    fila = con.execute(f"SELECT {_COLUMNAS} FROM facturas WHERE id = ?",
                       (id_,)).fetchone()
    return None if fila is None else _desde_fila(con, fila)


def listar(con: sqlite3.Connection, anio: int, trimestre: int | None = None,
           estado: str | None = None) -> list[Factura]:
    """Facturas del año (y trimestre 1-4 si se indica), por fecha e id."""
    if trimestre is None:
        desde, hasta = date(anio, 1, 1), date(anio + 1, 1, 1)
    else:
        if trimestre not in (1, 2, 3, 4):
            raise ValueError("El trimestre debe ser 1, 2, 3 o 4.")
        mes = 3 * (trimestre - 1) + 1
        desde = date(anio, mes, 1)
        hasta = date(anio + 1, 1, 1) if trimestre == 4 else date(anio, mes + 3, 1)
    sql = (f"SELECT {_COLUMNAS} FROM facturas WHERE fecha >= ? AND fecha < ?")
    args: list = [desde.isoformat(), hasta.isoformat()]
    if estado is not None:
        sql += " AND estado = ?"
        args.append(estado)
    sql += " ORDER BY fecha, id"
    return [_desde_fila(con, f) for f in con.execute(sql, args).fetchall()]


def cambiar_estado(con: sqlite3.Connection, id_: int, estado: str) -> None:
    if estado not in _ESTADOS:
        raise ValueError(f"Estado desconocido: {estado!r}")
    cur = con.execute("UPDATE facturas SET estado = ? WHERE id = ?", (estado, id_))
    if cur.rowcount == 0:
        raise KeyError(f"No existe la factura {id_}")
    con.commit()
