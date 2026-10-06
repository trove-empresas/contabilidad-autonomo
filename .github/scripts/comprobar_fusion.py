"""Decide, de forma determinista, si una PR puede fusionarse sola.

Reglas (procedimientos/fusion-automatica.md de `criterio`):
  1. La descripción declara «Riesgo: bajo» (y ningún otro nivel).
  2. Ningún archivo cambiado cae en una ruta protegida.
  (La condición «las comprobaciones pasan» la exige GitHub con la
  protección de rama + fusión automática, no este script.)

Uso: comprobar_fusion.py <rutas-protegidas.txt> <archivos.txt> <cuerpo.md>
Salida: «ELEGIBLE» (código 0) o «NO ELEGIBLE: motivo» (código 1).
Ante cualquier duda o error, no es elegible.
"""
import fnmatch
import re
import sys

NIVEL = re.compile(r"^[\s>*_\-]*riesgo[\s*_]*:[\s*_]*(bajo|medio|alto)\b", re.I | re.M)


def cargar_lineas(texto):
    return [l.strip() for l in texto.splitlines() if l.strip() and not l.strip().startswith("#")]


def riesgo_declarado(cuerpo):
    """Devuelve el nivel solo si hay UNA declaración o todas coinciden."""
    niveles = {m.group(1).lower() for m in NIVEL.finditer(cuerpo)}
    return niveles.pop() if len(niveles) == 1 else None


def es_protegida(ruta, patrones):
    ruta = ruta.removeprefix("./")
    for p in patrones:
        p = p.removeprefix("./")
        if p.endswith("/"):
            if ruta.startswith(p):
                return True
        elif "*" in p or "?" in p:
            if fnmatch.fnmatchcase(ruta.lower(), p.lower()):
                return True
        elif ruta == p:
            return True
    return False


def patrones_mal_escritos(patrones):
    """Rutas con comodín y «/» final (p. ej. «*/modelos/»): se leerían como
    carpeta literal y no protegerían nada. Hay que escribirlas «*/modelos/*»."""
    return [p for p in patrones if p.endswith("/") and ("*" in p or "?" in p)]


def evaluar(patrones, archivos, cuerpo):
    if not archivos:
        return False, "no hay archivos cambiados"
    if not patrones:
        return False, "no hay rutas protegidas declaradas"
    malos = patrones_mal_escritos(patrones)
    if malos:
        return False, ("rutas protegidas mal escritas (comodín con «/» final; "
                       "usa p. ej. «*/carpeta/*»): " + ", ".join(malos))
    if riesgo_declarado(cuerpo) != "bajo":
        return False, "la descripción no declara «Riesgo: bajo» de forma inequívoca"
    tocadas = [a for a in archivos if es_protegida(a, patrones)]
    if tocadas:
        return False, "toca rutas protegidas: " + ", ".join(tocadas)
    return True, ""


def main(argv):
    try:
        patrones = cargar_lineas(open(argv[1], encoding="utf-8").read())
        archivos = [l.strip() for l in open(argv[2], encoding="utf-8").read().splitlines() if l.strip()]
        cuerpo = open(argv[3], encoding="utf-8").read()
        ok, motivo = evaluar(patrones, archivos, cuerpo)
    except Exception as e:  # noqa: BLE001 - ante error, nunca elegible
        ok, motivo = False, f"error al comprobar: {e}"
    print("ELEGIBLE" if ok else f"NO ELEGIBLE: {motivo}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
