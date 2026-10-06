"""Pruebas de evaluar_fusion.sh, el paso que ejecuta el workflow.

Se ejecuta el script de verdad (bash con «-e», como en GitHub) con un «gh»
simulado que devuelve una PR inventada y apunta las órdenes que recibe.
No se llama a GitHub.
"""
import json
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest

AQUI = pathlib.Path(__file__).parent
SCRIPT = AQUI / "evaluar_fusion.sh"
BOT = "github-actions[bot]"
BAJO = "## Para Gonzalo\n- **Riesgo:** bajo — solo texto\n"

GH_SIMULADO = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["SIM"]
args = sys.argv[1:]
with open(os.path.join(d, "ordenes.log"), "a", encoding="utf-8") as f:
    f.write(" ".join(args) + "\n")
if args[0] == "api":
    ruta = [a for a in args[1:] if not a.startswith("--")][0]
    nombre = "archivos.json" if ruta.endswith("/files") else "pr.json"
    sys.stdout.write(open(os.path.join(d, nombre), encoding="utf-8").read())
elif args[:2] == ["pr", "merge"]:
    if "--disable-auto" in args and os.path.exists(os.path.join(d, "falla_desactivar")):
        sys.exit(1)
else:
    sys.exit(f"orden no simulada: {args}")
'''


def pr(cuerpo=BAJO, borrador=False, estado="open", activada_por=None, origen="o/r"):
    return {
        "body": cuerpo, "draft": borrador, "state": estado, "changed_files": 1,
        "head": {"sha": "abc123", "repo": {"full_name": origen}},
        "auto_merge": {"enabled_by": {"login": activada_por}} if activada_por else None,
    }


class EvaluarFusion(unittest.TestCase):
    def ejecutar(self, datos_pr, archivos, falla_desactivar=False):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "pr.json").write_text(json.dumps(datos_pr), encoding="utf-8")
        (d / "archivos.json").write_text(json.dumps([{"filename": a} for a in archivos]), encoding="utf-8")
        if falla_desactivar:
            (d / "falla_desactivar").touch()
        bin_ = d / "bin"
        bin_.mkdir()
        (bin_ / "gh").write_text(GH_SIMULADO, encoding="utf-8")
        (bin_ / "gh").chmod(stat.S_IRWXU)
        env = dict(os.environ, SIM=str(d), PATH=f"{bin_}:{os.environ['PATH']}",
                   REPO="o/r", PR="7", GITHUB_STEP_SUMMARY=str(d / "resumen.md"))
        res = subprocess.run(["bash", "-e", str(SCRIPT)], env=env, capture_output=True, text=True)
        ordenes = (d / "ordenes.log").read_text(encoding="utf-8") if (d / "ordenes.log").exists() else ""
        resumen = (d / "resumen.md").read_text(encoding="utf-8") if (d / "resumen.md").exists() else ""
        return res, ordenes, resumen

    # --- PR no elegible: verde y con el motivo ---

    def test_no_elegible_por_riesgo_sale_en_verde_con_motivo(self):
        res, ordenes, resumen = self.ejecutar(pr(cuerpo="- **Riesgo: alto** — fiscal"), ["README.md"])
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("requiere fusión manual de Gonzalo", resumen)
        self.assertIn("Riesgo: bajo", resumen)
        self.assertIn("::notice", res.stdout)
        self.assertNotIn("--auto ", ordenes)

    def test_no_elegible_por_ruta_protegida_sale_en_verde_con_motivo(self):
        res, ordenes, resumen = self.ejecutar(pr(), ["CLAUDE.md"])
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("requiere fusión manual de Gonzalo", resumen)
        self.assertIn("CLAUDE.md", resumen)
        self.assertNotIn("--auto ", ordenes)

    def test_borrador_no_elegible_en_verde(self):
        res, ordenes, resumen = self.ejecutar(pr(borrador=True), ["README.md"])
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("borrador", resumen)
        self.assertNotIn("--auto ", ordenes)

    def test_fork_no_elegible_en_verde(self):
        res, ordenes, _ = self.ejecutar(pr(origen="otro/r"), ["README.md"])
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertNotIn("--auto ", ordenes)

    # --- PR elegible: sigue activando la fusión automática ---

    def test_elegible_activa_la_fusion_automatica_atada_al_commit(self):
        res, ordenes, resumen = self.ejecutar(pr(), ["README.md"])
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("pr merge 7 --repo o/r --auto --squash --match-head-commit abc123", ordenes)
        self.assertIn("ELEGIBLE", resumen)

    # --- Fusión automática activada a mano: no se toca ---

    def test_no_desactiva_la_activada_a_mano_en_pr_no_elegible(self):
        res, ordenes, resumen = self.ejecutar(pr(cuerpo="Riesgo: alto", activada_por="gonzalo"), ["CLAUDE.md"])
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertNotIn("--disable-auto", ordenes)
        self.assertIn("activó a mano gonzalo", resumen)

    def test_no_cambia_la_activada_a_mano_en_pr_elegible(self):
        res, ordenes, resumen = self.ejecutar(pr(activada_por="gonzalo"), ["README.md"])
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertNotIn("--disable-auto", ordenes)
        self.assertNotIn("--auto ", ordenes)
        self.assertIn("activó a mano gonzalo", resumen)

    # --- Fusión automática activada por el propio automatismo ---

    def test_desactiva_la_del_automatismo_si_deja_de_ser_elegible(self):
        res, ordenes, _ = self.ejecutar(pr(cuerpo="Riesgo: medio", activada_por=BOT), ["README.md"])
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("pr merge 7 --repo o/r --disable-auto", ordenes)
        self.assertNotIn("--auto ", ordenes)

    def test_reactiva_la_del_automatismo_si_sigue_elegible(self):
        res, ordenes, _ = self.ejecutar(pr(activada_por=BOT), ["README.md"])
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertLess(ordenes.index("--disable-auto"), ordenes.index("--auto --squash"))

    # --- Rojo solo cuando algo va mal ---

    def test_rojo_si_no_puede_desactivar_la_del_automatismo(self):
        res, ordenes, _ = self.ejecutar(pr(cuerpo="Riesgo: alto", activada_por=BOT), ["README.md"],
                                        falla_desactivar=True)
        self.assertNotEqual(res.returncode, 0)
        self.assertNotIn("--auto ", ordenes)

    def test_rojo_si_el_script_de_decision_falla(self):
        res, ordenes, _ = self.ejecutar(pr(cuerpo=None), [])  # sin archivos: no elegible, no error
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        res, ordenes, _ = self.ejecutar({"roto": True}, ["README.md"])  # respuesta de la API inesperada
        self.assertNotEqual(res.returncode, 0)
        self.assertNotIn("--auto ", ordenes)


if __name__ == "__main__":
    unittest.main()
