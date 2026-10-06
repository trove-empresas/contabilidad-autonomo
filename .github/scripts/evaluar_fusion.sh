#!/usr/bin/env bash
# Evalúa una PR y, si es elegible, activa la fusión automática.
# Lo ejecuta .github/workflows/fusion-automatica.yml, siempre en su versión de
# la rama principal. Pruebas: test_evaluar_fusion.py.
#
# Entrada (variables de entorno): GH_TOKEN, REPO (dueño/repo), PR (número).
# Resultado:
#   - Código 0 si ha podido decidir, sea elegible o no. Una PR no elegible
#     es lo normal (requiere fusión manual de Gonzalo), no un fallo.
#   - Otro código solo si algo ha ido mal (API, script de decisión...).
#
# Fusión automática ya activada:
#   - Si la activó este automatismo, se desactiva antes de volver a evaluar.
#   - Si la activó una persona a mano, NO se toca, sea elegible o no.
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
BOT="github-actions[bot]"
RESUMEN="${GITHUB_STEP_SUMMARY:-/dev/null}"
tmp="$(mktemp -d)"

informar() {  # informar <nivel notice|error> <texto>
  echo "::$1 title=Fusión automática::$2"
  echo "### Fusión automática: $2" >> "$RESUMEN"
}

# 1. Leer la PR de la API (se trata como datos; no se ejecuta nada de ella).
gh api "repos/$REPO/pulls/$PR" > "$tmp/pr.json"
if ! jq -e '(.state | type == "string") and (.head.sha | type == "string")' "$tmp/pr.json" > /dev/null; then
  informar error "ERROR: la API devolvió una PR sin estado o sin commit; no se decide nada."
  exit 1
fi
jq -r '.body // ""' "$tmp/pr.json" > "$tmp/cuerpo.md"
gh api --paginate "repos/$REPO/pulls/$PR/files" \
  | jq -r '.[] | .filename, (.previous_filename // empty)' > "$tmp/archivos.txt"

campo() { jq -r "$1" "$tmp/pr.json"; }
sha="$(campo '.head.sha')"
estado="$(campo '.state')"
borrador="$(campo '.draft')"
num_archivos="$(campo '.changed_files // 0')"
repo_origen="$(campo '.head.repo.full_name // ""')"
activada_por="$(campo '.auto_merge.enabled_by.login // ""')"

# 2. Fusión automática que ya hubiera.
manual=""
if [ "$activada_por" = "$BOT" ]; then
  if ! gh pr merge "$PR" --repo "$REPO" --disable-auto; then
    informar error "ERROR: no se pudo desactivar la fusión automática que activó este automatismo; no se decide nada."
    exit 1
  fi
elif [ -n "$activada_por" ]; then
  manual="$activada_por"
fi

# 3. Decidir. El script devuelve 0 = elegible, 1 = no elegible, otro = error.
if [ "$estado" != "open" ]; then
  rc=1; motivo="NO ELEGIBLE: la PR no está abierta"
elif [ "$borrador" != "false" ]; then
  rc=1; motivo="NO ELEGIBLE: la PR es un borrador"
elif [ "$repo_origen" != "$REPO" ]; then
  rc=1; motivo="NO ELEGIBLE: la PR viene de otro repositorio (fork)"
elif [ "$num_archivos" -ge 3000 ]; then
  rc=1; motivo="NO ELEGIBLE: demasiados archivos para listarlos todos"
else
  rc=0
  motivo="$(python3 "$AQUI/comprobar_fusion.py" "$AQUI/../rutas-protegidas.txt" \
    "$tmp/archivos.txt" "$tmp/cuerpo.md")" || rc=$?
fi

nota_manual=""
if [ -n "$manual" ]; then
  nota_manual=" La fusión automática que activó a mano $manual se deja como está."
fi

# 4. Actuar según la decisión.
case "$rc" in
  0)
    if [ -n "$manual" ]; then
      informar notice "ELEGIBLE.$nota_manual"
    else
      gh pr merge "$PR" --repo "$REPO" --auto --squash --match-head-commit "$sha"
      informar notice "ELEGIBLE: fusión automática activada; GitHub fusionará cuando pasen las comprobaciones."
    fi
    ;;
  1)
    informar notice "${motivo/NO ELEGIBLE: /NO ELEGIBLE, requiere fusión manual de Gonzalo. Motivo: }.$nota_manual"
    ;;
  *)
    informar error "ERROR al comprobar (código $rc): $motivo"
    exit 1
    ;;
esac
