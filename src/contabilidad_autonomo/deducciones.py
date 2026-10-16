"""Guardar y leer lo que el usuario declara de cada factura recibida (issue #27).

Aquí no se calcula nada fiscal: solo se persiste y se reconstruyen los
``DatosDeduccion`` y las fechas de devengo que ``modelo_303.calcular_303``
recibe. Una factura recibida **sin** fila guardada no aparece en
``deducciones`` y el 303 la deja **pendiente** (no suma).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from contabilidad_autonomo.facturas import RECIBIDA, Factura, listar
from contabilidad_autonomo.modelo_303 import Resultado303, DatosDeduccion, calcular_303


@dataclass(frozen=True)
class DeduccionGuardada:
    """Lo guardado de una factura: los datos del 303 y el devengo corregido."""

    datos: DatosDeduccion
    fecha_devengo: date | None = None  # corrige la fecha de la factura


def _iso(d: date | None) -> str | None:
    return None if d is None else d.isoformat()


def guardar(con: sqlite3.Connection, factura_id: int, datos: DatosDeduccion,
            fecha_devengo: date | None = None) -> None:
    """Guarda (o reemplaza) lo declarado de una factura recibida."""
    fila = con.execute("SELECT tipo FROM facturas WHERE id = ?", (factura_id,)).fetchone()
    if fila is None:
        raise KeyError(f"No existe la factura {factura_id}")
    if fila[0] != RECIBIDA:
        raise ValueError("Solo las facturas recibidas llevan datos de deducción.")
    anio, trim = datos.deducir_en if datos.deducir_en else (None, None)
    try:
        con.execute(
            """INSERT OR REPLACE INTO datos_deduccion (factura_id, afectacion,
                simplificada, tipo_isp, fecha_recepcion, fecha_devengo,
                deducir_anio, deducir_trimestre) VALUES (?,?,?,?,?,?,?,?)""",
            (factura_id, datos.afectacion, int(datos.simplificada),
             None if datos.tipo_isp is None else str(datos.tipo_isp),
             _iso(datos.fecha_recepcion), _iso(fecha_devengo), anio, trim))
        con.commit()
    except Exception:
        con.rollback()
        raise


def leer(con: sqlite3.Connection, factura_id: int) -> DeduccionGuardada | None:
    fila = con.execute(
        """SELECT afectacion, simplificada, tipo_isp, fecha_recepcion,
                  fecha_devengo, deducir_anio, deducir_trimestre
           FROM datos_deduccion WHERE factura_id = ?""", (factura_id,)).fetchone()
    return None if fila is None else _desde_fila(fila)


def _desde_fila(fila: tuple) -> DeduccionGuardada:
    afect, simp, tipo, recep, devengo, anio, trim = fila
    datos = DatosDeduccion(
        afectacion=afect, simplificada=bool(simp),
        tipo_isp=None if tipo is None else Decimal(tipo),
        fecha_recepcion=None if recep is None else date.fromisoformat(recep),
        deducir_en=None if anio is None else (anio, trim))
    return DeduccionGuardada(
        datos, None if devengo is None else date.fromisoformat(devengo))


def borrar(con: sqlite3.Connection, factura_id: int) -> None:
    """Quita lo declarado: la factura vuelve a quedar pendiente en el 303."""
    con.execute("DELETE FROM datos_deduccion WHERE factura_id = ?", (factura_id,))
    con.commit()


def calcular_303_guardado(con: sqlite3.Connection, anio: int, trimestre: int,
                          titular_nif: str, **kw) -> Resultado303:
    """Calcula el 303 con las facturas y los datos de deducción guardados.

    Se pasan todas las facturas guardadas hasta el final del año pedido (las
    tardías pueden deducirse hasta 4 años después, art. 99.Tres LIVA, y el
    devengo corregido puede diferir de la fecha); ``calcular_303`` decide
    cuáles entran en el trimestre.
    """
    primera = con.execute("SELECT MIN(fecha) FROM facturas").fetchone()[0]
    facturas: list[Factura] = []
    if primera is not None:
        for a in range(date.fromisoformat(primera).year, anio + 1):
            facturas.extend(listar(con, a))
    ids = [f.id for f in facturas if f.tipo == RECIBIDA]
    guardadas = {i: leer(con, i) for i in ids}
    deducciones = {i: g.datos for i, g in guardadas.items() if g}
    devengos = {i: g.fecha_devengo for i, g in guardadas.items()
                if g and g.fecha_devengo}
    return calcular_303(facturas, anio, trimestre, titular_nif,
                        deducciones=deducciones, fechas_devengo=devengos, **kw)
