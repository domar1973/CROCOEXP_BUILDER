#!/usr/bin/env bash
######################################################
##
## CROCO EXPERIMENT BUILDER (UNTDF) - compile launcher
##
## Uso:
##   cd /opt/CROCO_EXPERIMENTS
##   source setup.sh
##   ./compile_experiment.sh EXP_A
##
## Compila usando el jobcomp "oficial" de la distro CROCO,
## aplicando overrides desde experiments/EXP_A/EXP/
## y dejando el build bajo experiments/EXP_A/build/
##
######################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXP_BASE="${SCRIPT_DIR}/experiments"
TEMPLATE="${EXP_BASE}/001_TEMPLATE_EXPERIMENT"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/setup.sh"

NEW_NAME="${1:-}"
if [[ -z "${NEW_NAME}" ]]; then
  echo "Uso: $0 <nuevo_experimento>"
  echo "Ej:  $0 EXP_MAREA_001"
  exit 1
fi

# Nombre seguro (simple, sin espacios)
if [[ ! "${NEW_NAME}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ERROR: nombre inválido: ${NEW_NAME}"
  echo "Permitidos: letras, números, punto, guion, guion bajo."
  exit 1
fi

if [[ ! -d "${TEMPLATE}" ]]; then
  echo "ERROR: no existe el template: ${TEMPLATE}"
  exit 1
fi

DEST="${EXP_BASE}/${NEW_NAME}"
if [[ -e "${DEST}" ]]; then
  echo "ERROR: ya existe: ${DEST}"
  exit 1
fi

# Paths CROCO distro
CROCO_OCEAN="${SCRIPT_DIR}/${version}/OCEAN"
CROCO_IN_SRC="${CROCO_OCEAN}/croco.in"
CPPDEFS_SRC="${CROCO_OCEAN}/cppdefs.h"
PARAM_SRC="${CROCO_OCEAN}/param.h"
ANALYTICAL_SRC="${CROCO_OCEAN}/analytical.F"

for f in "${CROCO_IN_SRC}" "${CPPDEFS_SRC}" "${PARAM_SRC}" "${ANALYTICAL_SRC}"; do
  [[ -f "${f}" ]] || { echo "ERROR: no existe en distro: ${f}"; exit 1; }
done

echo "Creando experimento: ${NEW_NAME}"
cp -a "${TEMPLATE}" "${DEST}"

# Crear dirs de runtime (por si no estaban o fueron limpiados)
mkdir -p "${DEST}/build" "${DEST}/LOG"

# -------------------------------------------------------------------
# EXP/: Copiar archivos base desde la distro (intocable)
# -------------------------------------------------------------------
mkdir -p "${DEST}/EXP"

cp -f "${ANALYTICAL_SRC}" "${DEST}/EXP/analytical.F"
cp -f "${CPPDEFS_SRC}"     "${DEST}/EXP/cppdefs.h"
cp -f "${PARAM_SRC}"       "${DEST}/EXP/param.h"

# -------------------------------------------------------------------
# croco.in: run.env + croco.in.template (canon)
# - Guardamos el croco.in original como referencia (croco.in.base)
# - Generamos croco.in.template reemplazando paths por placeholders
# -------------------------------------------------------------------
cp -f "${CROCO_IN_SRC}" "${DEST}/EXP/croco.in.base"
cp -f "${CROCO_IN_SRC}" "${DEST}/EXP/croco.in.template"

# sed -i portable (GNU/BSD)
SED_INPLACE() {
  # usage: SED_INPLACE 's/a/b/' file
  local expr="$1"
  local file="$2"
  if sed --version >/dev/null 2>&1; then
    sed -i "${expr}" "${file}"
  else
    # macOS/BSD sed requiere extensión (vacía)
    sed -i '' "${expr}" "${file}"
  fi
}

TPL="${DEST}/EXP/croco.in.template"

# Normalizamos a nuestra convención: rutas relativas a RUN_DIR
# USER EDIT ZONE: placeholders
# Nota: si alguna key no existe en el croco.in de la versión, sed no cambia nada (ok).
SED_INPLACE 's|^[[:space:]]*TITLE[[:space:]]*==.*|TITLE   == @RUN_TITLE@|I' "${TPL}"

SED_INPLACE 's|^[[:space:]]*GRDNAME[[:space:]]*==.*|GRDNAME == GRD/@GRD_FILE@|I' "${TPL}"
SED_INPLACE 's|^[[:space:]]*ININAME[[:space:]]*==.*|ININAME == INIT/@INI_FILE@|I' "${TPL}"
SED_INPLACE 's|^[[:space:]]*FRCNAME[[:space:]]*==.*|FRCNAME == FORC/@FRC_FILE@|I' "${TPL}"

# Opcionales: los dejamos con placeholders; el runner puede validar si se usan o no.
SED_INPLACE 's|^[[:space:]]*CLMNAME[[:space:]]*==.*|CLMNAME == INIT/@CLM_FILE@|I' "${TPL}"
SED_INPLACE 's|^[[:space:]]*BRYNAME[[:space:]]*==.*|BRYNAME == INIT/@BRY_FILE@|I' "${TPL}"
SED_INPLACE 's|^[[:space:]]*TIDENAME[[:space:]]*==.*|TIDENAME == FORC/@TIDE_FILE@|I' "${TPL}"

SED_INPLACE 's|^[[:space:]]*HISNAME[[:space:]]*==.*|HISNAME == OUT/@HIS_FILE@|I' "${TPL}"
SED_INPLACE 's|^[[:space:]]*AVGNAME[[:space:]]*==.*|AVGNAME == OUT/@AVG_FILE@|I' "${TPL}"
SED_INPLACE 's|^[[:space:]]*RSTNAME[[:space:]]*==.*|RSTNAME == OUT/@RST_FILE@|I' "${TPL}"

# Control básico (si querés que también venga de run.env; si no, comentá estas 6 líneas)
SED_INPLACE 's|^[[:space:]]*DT[[:space:]]*==.*|DT      == @DT@|I' "${TPL}"
SED_INPLACE 's|^[[:space:]]*NTIMES[[:space:]]*==.*|NTIMES  == @NTIMES@|I' "${TPL}"
SED_INPLACE 's|^[[:space:]]*NDTFAST[[:space:]]*==.*|NDTFAST == @NDTFAST@|I' "${TPL}"
SED_INPLACE 's|^[[:space:]]*NHIS[[:space:]]*==.*|NHIS    == @NHIS@|I' "${TPL}"
SED_INPLACE 's|^[[:space:]]*NAVG[[:space:]]*==.*|NAVG    == @NAVG@|I' "${TPL}"
SED_INPLACE 's|^[[:space:]]*NRST[[:space:]]*==.*|NRST    == @NRST@|I' "${TPL}"

# -------------------------------------------------------------------
# run.env: único archivo que edita el usuario (y el GPT)
# -------------------------------------------------------------------
cat > "${DEST}/EXP/run.env" <<EOF
# =========================================================
# run.env (CANÓNICO)
# Editá este archivo para configurar insumos/salidas del run.
# El runner renderiza croco.in desde croco.in.template.
#
# Convención de directorios (relativos al RUN_DIR):
#   GRD/   : grilla/batimetría
#   INIT/  : condiciones iniciales (y CLM/BRY si aplica)
#   FORC/  : forzantes (atm, fluxes, bulk, mareas, etc.)
#   OUT/   : salida local del run
# =========================================================

# Obligatorios
RUN_TITLE="${NEW_NAME}"
GRD_FILE="grid.nc"
INI_FILE="ini.nc"
FRC_FILE="forc.nc"

# Opcionales (dejar vacío si no aplica)
CLM_FILE=""
BRY_FILE=""
TIDE_FILE=""

# Salidas (opcional)
HIS_FILE="his.nc"
AVG_FILE="avg.nc"
RST_FILE="rst.nc"

# Control básico (opcional; 0 => conservar valores del template base)
DT=0
NTIMES=0
NDTFAST=0
NHIS=0
NAVG=0
NRST=0
EOF

# -------------------------------------------------------------------
# README del experimento (metadata)
# -------------------------------------------------------------------
cat > "${DEST}/README.md" <<EOF
###############################################################################
##                                                                           ##
##                   CROCO EXPERIMENTS BUILDER                               ##
##  Environment for configuration and running of CROCO numeric experiments   ##
##                                                                           ##
##     Universidad Nacional de Tierra del Fuego - Ushuaia - Argentina        ##
##                                                                           ##
##           Daniel Badagnani (dbadagnani@untdf.edu.ar)                      ##
##                                                                           ##
###############################################################################

> METADATA

name=${NEW_NAME}
created_at=$(date -Is)
template=001_TEMPLATE_EXPERIMENT
CROCO_version=${version}

> USER DESCRIPTION OF THE EXPERIMENT

EOF

echo "OK: ${DEST}"
echo
echo "Siguiente flujo sugerido:"
echo "  cd CROCO_EXPERIMENTS"
echo "  source setup.sh"
echo "  ./compile_experiment.sh ${NEW_NAME}"
echo "  ./run_experiment.sh ${NEW_NAME}        # serial"
echo "  ./run_experiment.sh ${NEW_NAME} -n 8   # MPI (si aplica)"
echo
echo "Configuración:"
echo "  - Editá: ${DEST}/EXP/run.env"
echo "  - Template: ${DEST}/EXP/croco.in.template (rara vez se toca)"
echo "  - Referencia: ${DEST}/EXP/croco.in.base (solo lectura)"
echo
echo "¡Que te diviertas!"
