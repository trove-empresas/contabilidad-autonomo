import pathlib
import tempfile
import unittest

from comprobar_fusion import es_protegida, main, evaluar, patrones_mal_escritos, riesgo_declarado

P = ["CLAUDE.md", ".github/", "casos_validados/", ".env.*", "*secret*", "src/fiscal/"]
BAJO = "## Para Gonzalo\n- **Riesgo:** bajo — texto\n"


class Rutas(unittest.TestCase):
    def test_protegidas(self):
        for r in ["CLAUDE.md", ".github/workflows/x.yml", "casos_validados/a.json",
                  ".env.local", "src/mi_SECRET.py", "src/fiscal/iva.py", "./CLAUDE.md"]:
            self.assertTrue(es_protegida(r, P), r)

    def test_no_protegidas(self):
        for r in ["README.md", "docs/CLAUDE.md", "src/ui/a.py", "src/fiscal_no.py", "github/x"]:
            self.assertFalse(es_protegida(r, P), r)


class Riesgo(unittest.TestCase):
    def test_variantes_bajo(self):
        for t in ["Riesgo: bajo", "- **Riesgo:** bajo — por X", "**Riesgo: bajo**", "riesgo : BAJO"]:
            self.assertEqual(riesgo_declarado(t), "bajo", t)

    def test_no_bajo(self):
        self.assertEqual(riesgo_declarado("Riesgo: medio"), "medio")
        self.assertIsNone(riesgo_declarado("sin nada"))
        self.assertIsNone(riesgo_declarado("<bajo / medio / alto>"))
        self.assertIsNone(riesgo_declarado("Riesgo: bajo\nRiesgo: alto"))


class Evaluar(unittest.TestCase):
    def test_elegible(self):
        self.assertTrue(evaluar(P, ["src/ui/a.py", "README.md"], BAJO)[0])

    def test_ruta_protegida_gana_a_riesgo_bajo(self):
        ok, m = evaluar(P, ["src/ui/a.py", ".github/workflows/a.yml"], BAJO)
        self.assertFalse(ok)
        self.assertIn(".github/workflows/a.yml", m)

    def test_riesgo_no_bajo(self):
        self.assertFalse(evaluar(P, ["a.py"], "Riesgo: medio")[0])

    def test_sin_archivos_o_sin_rutas(self):
        self.assertFalse(evaluar(P, [], BAJO)[0])
        self.assertFalse(evaluar([], ["a.py"], BAJO)[0])


class PatronesMalEscritos(unittest.TestCase):
    """Una ruta como «*/modelos/» no protegería nada: debe ser un error."""

    def test_detecta_comodin_con_barra_final(self):
        self.assertEqual(patrones_mal_escritos(["CLAUDE.md", "*/modelos/", "src/*/"]),
                         ["*/modelos/", "src/*/"])
        self.assertEqual(patrones_mal_escritos(["a?/"]), ["a?/"])

    def test_rutas_correctas_no_se_marcan(self):
        self.assertEqual(patrones_mal_escritos(P + ["*/modelos/*", "./src/x/"]), [])

    def test_evaluar_no_es_elegible_con_un_patron_mal_escrito(self):
        ok, m = evaluar(P + ["*/modelos/"], ["src/ui/a.py"], BAJO)
        self.assertFalse(ok)
        self.assertIn("*/modelos/", m)


class CodigoDeSalida(unittest.TestCase):
    """0 = elegible, 1 = no elegible (decisión normal), 2 = error al comprobar."""

    def archivos(self, rutas, cambiados, cuerpo):
        d = pathlib.Path(tempfile.mkdtemp())
        for nombre, texto in [("r.txt", rutas), ("a.txt", cambiados), ("c.md", cuerpo)]:
            (d / nombre).write_text(texto, encoding="utf-8")
        return ["x", str(d / "r.txt"), str(d / "a.txt"), str(d / "c.md")]

    def test_elegible_0(self):
        self.assertEqual(main(self.archivos("CLAUDE.md\n", "README.md\n", BAJO)), 0)

    def test_no_elegible_1(self):
        self.assertEqual(main(self.archivos("CLAUDE.md\n", "CLAUDE.md\n", BAJO)), 1)

    def test_error_2(self):
        self.assertEqual(main(["x", "/no/existe", "/no/existe", "/no/existe"]), 2)


if __name__ == "__main__":
    unittest.main()
