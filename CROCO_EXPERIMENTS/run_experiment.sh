#!/bin/bash
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

usage() {
  cat <<'EOF'
Uso:
  ./run_experiment.sh <EXP_NAME> [opciones]

Opciones:
  -n, --np <N>              Ejecutar en MPI con N procesos
  --launcher <cmd>          Launcher MPI (default: mpirun). Ej: mpirun, mpiexec, srun
  --run-id <TAG>            Tag adicional para el nombre del RUN_DIR
  --env <path>              Archivo run.env alternativo (default: EXP/run.env)
  --template <path>         croco.in.template alternativo (default: EXP/croco.in.template)
  --exe <path>              Ejecutable alternativo (default: build/croco)
  --dry-run                 No ejecuta; muestra acciones
  -h, --help                Ayuda
EOF
}

EXP_NAME="${1:-}"
shift || true
if [[ -z "${EXP_NAME}" || "${EXP_NAME}" == "-h" || "${EXP_NAME}" == "--help" ]]; then
  usage
  exit 0
fi

NP=""
LAUNCHER="mpirun"
RUN_TAG=""
ENV_FILE=""
TEMPLATE_FILE=""
EXE_OVERRIDE=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--np) NP="${2:-}"; shift 2;;
    --launcher) LAUNCHER="${2:-}"; shift 2;;
    --run-id) RUN_TAG="${2:-}"; shift 2;;
    --env) ENV_FILE="${2:-}"; shift 2;;
    --template) TEMPLATE_FILE="${2:-}"; shift 2;;
    --exe) EXE_OVERRIDE="${2:-}"; shift 2;;
    --dry-run) DRY_RUN=1; shift 1;;
    -h|--help) usage; exit 0;;
    *) echo "Opción desconocida: $1"; usage; exit 1;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${ROOT_DIR}/setup.sh"

# Resolver experiments dir (compatibilidad)
if [[ -z "${CROCOEXP_EXPERIMENTS_DIR:-}" ]]; then
  if [[ -n "${MSOT_EXPERIMENTS_DIR:-}" ]]; then
    CROCOEXP_EXPERIMENTS_DIR="${MSOT_EXPERIMENTS_DIR}"
  else
    CROCOEXP_EXPERIMENTS_DIR="${CROCOEXP_HOME}/experiments"
  fi
fi

EXP_DIR="${CROCOEXP_EXPERIMENTS_DIR}/${EXP_NAME}"
EXP_CFG="${EXP_DIR}/EXP"
BUILD_DIR="${EXP_DIR}/build"
OUT_BASE="${EXP_DIR}/OUT"
LOG_DIR="${EXP_DIR}/LOG"

[[ -d "${EXP_DIR}" ]] || { echo "ERROR: no existe ${EXP_DIR}"; exit 1; }
[[ -d "${EXP_CFG}" ]] || { echo "ERROR: falta ${EXP_CFG}"; exit 1; }
[[ -d "${BUILD_DIR}" ]] || { echo "ERROR: falta ${BUILD_DIR} (¿compilaste?)"; exit 1; }

mkdir -p "${OUT_BASE}" "${LOG_DIR}"

EXE="${EXE_OVERRIDE:-${BUILD_DIR}/croco}"
[[ -x "${EXE}" ]] || { echo "ERROR: no encuentro ejecutable: ${EXE}"; exit 1; }

ENV_FILE="${ENV_FILE:-${EXP_CFG}/run.env}"
TEMPLATE_FILE="${TEMPLATE_FILE:-${EXP_CFG}/croco.in.template}"

[[ -f "${ENV_FILE}" ]] || { echo "ERROR: falta ${ENV_FILE}"; exit 1; }
[[ -f "${TEMPLATE_FILE}" ]] || { echo "ERROR: falta ${TEMPLATE_FILE}"; exit 1; }

TS="$(date +%Y%m%d_%H%M%S)"
RUN_ID="run_${TS}"
if [[ -n "${RUN_TAG}" ]]; then RUN_ID="${RUN_ID}_${RUN_TAG}"; fi

RUN_DIR="${OUT_BASE}/${RUN_ID}"
mkdir -p "${RUN_DIR}/OUT"

RUN_LOG="${LOG_DIR}/run_${EXP_NAME}_${RUN_ID}.log"

die() { echo "ERROR: $*" >&2; exit 1; }

need_var() {
  local v="$1"
  [[ -n "${!v:-}" ]] || die "run.env: falta variable obligatoria: ${v}"
}

# shellcheck disable=SC1090
source "${ENV_FILE}"

# Defaults
HIS_FILE="${HIS_FILE:-his.nc}"
RST_FILE="${RST_FILE:-rst.nc}"
AVG_FILE="${AVG_FILE:-avg.nc}"

DT="${DT:-0}"
NTIMES="${NTIMES:-0}"
NDTFAST="${NDTFAST:-0}"
NHIS="${NHIS:-0}"
NRST="${NRST:-0}"
NAVG="${NAVG:-0}"

CLM_FILE="${CLM_FILE:-}"
BRY_FILE="${BRY_FILE:-}"
TIDE_FILE="${TIDE_FILE:-}"

need_var RUN_TITLE
need_var GRD_FILE
need_var INI_FILE
need_var FRC_FILE

# Link inputs into RUN_DIR
for d in GRD INIT FORC; do
  if [[ -d "${EXP_DIR}/${d}" ]]; then
    ln -sfn "${EXP_DIR}/${d}" "${RUN_DIR}/${d}"
  fi
done

# Render template
CROCO_IN="${RUN_DIR}/croco.in"

# Usamos sed con delimitador | para tolerar rutas con /
sed \
  -e "s|@RUN_TITLE@|${RUN_TITLE}|g" \
  -e "s|@GRD_FILE@|${GRD_FILE}|g" \
  -e "s|@INI_FILE@|${INI_FILE}|g" \
  -e "s|@FRC_FILE@|${FRC_FILE}|g" \
  -e "s|@HIS_FILE@|${HIS_FILE}|g" \
  -e "s|@RST_FILE@|${RST_FILE}|g" \
  -e "s|@AVG_FILE@|${AVG_FILE}|g" \
  -e "s|@DT@|${DT}|g" \
  -e "s|@NTIMES@|${NTIMES}|g" \
  -e "s|@NDTFAST@|${NDTFAST}|g" \
  -e "s|@NHIS@|${NHIS}|g" \
  -e "s|@NRST@|${NRST}|g" \
  -e "s|@NAVG@|${NAVG}|g" \
  -e "s|@CLM_FILE@|${CLM_FILE}|g" \
  -e "s|@BRY_FILE@|${BRY_FILE}|g" \
  -e "s|@TIDE_FILE@|${TIDE_FILE}|g" \
  "${TEMPLATE_FILE}" > "${CROCO_IN}"

# Condicionales: si *_FILE vacío, comentar líneas para que CROCO no vea paths incompletos
comment_if_empty() {
  local varname="$1"
  local key="$2"   # e.g. CLMNAME
  if [[ -z "${!varname:-}" ]]; then
    # Comentar la línea si existe y no está ya comentada
    # (fortran-style: ! al comienzo)
    sed -i -E "s|^([[:space:]]*)(${key}[[:space:]]*==.*)|\1!\2|I" "${CROCO_IN}" 2>/dev/null \
      || sed -i '' -E "s|^([[:space:]]*)(${key}[[:space:]]*==.*)|\1!\2|I" "${CROCO_IN}"
  fi
}

comment_if_empty CLM_FILE  CLMNAME
comment_if_empty BRY_FILE  BRYNAME
comment_if_empty TIDE_FILE TIDENAME

# Validar insumos
[[ -f "${RUN_DIR}/GRD/${GRD_FILE}" ]] || die "No existe GRD/${GRD_FILE}"
[[ -f "${RUN_DIR}/INIT/${INI_FILE}" ]] || die "No existe INIT/${INI_FILE}"
[[ -f "${RUN_DIR}/FORC/${FRC_FILE}" ]] || die "No existe FORC/${FRC_FILE}"

if [[ -n "${CLM_FILE}" ]]; then [[ -f "${RUN_DIR}/INIT/${CLM_FILE}" ]] || die "No existe INIT/${CLM_FILE}"; fi
if [[ -n "${BRY_FILE}" ]]; then [[ -f "${RUN_DIR}/INIT/${BRY_FILE}" ]] || die "No existe INIT/${BRY_FILE}"; fi
if [[ -n "${TIDE_FILE}" ]]; then [[ -f "${RUN_DIR}/FORC/${TIDE_FILE}" ]] || die "No existe FORC/${TIDE_FILE}"; fi

# Snapshot
SNAP="${RUN_DIR}/CONFIG_SNAPSHOT"
mkdir -p "${SNAP}"
cp -f "${ENV_FILE}" "${SNAP}/run.env"
cp -f "${TEMPLATE_FILE}" "${SNAP}/croco.in.template"
cp -f "${CROCO_IN}" "${SNAP}/croco.in.rendered"
[[ -f "${EXP_CFG}/cppdefs.h" ]] && cp -f "${EXP_CFG}/cppdefs.h" "${SNAP}/cppdefs.h"
[[ -f "${EXP_CFG}/param.h"   ]] && cp -f "${EXP_CFG}/param.h"   "${SNAP}/param.h"

echo
echo "Run: ${EXP_NAME}"
echo "RUN_DIR      : ${RUN_DIR}"
echo "Executable   : ${EXE}"
echo "croco.in     : ${CROCO_IN}"
echo "log          : ${RUN_LOG}"
echo "MPI np       : ${NP:-serial}"
echo "launcher     : ${LAUNCHER}"
echo

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "[DRY-RUN] No ejecuto el modelo."
  exit 0
fi

(
  cd "${RUN_DIR}"
  if [[ -n "${NP}" ]]; then
    command -v "${LAUNCHER}" >/dev/null 2>&1 || die "No encuentro launcher: ${LAUNCHER}"
    echo "CMD: ${LAUNCHER} -np ${NP} ${EXE} croco.in"
    "${LAUNCHER}" -np "${NP}" "${EXE}" croco.in
  else
    echo "CMD: ${EXE} croco.in"
    "${EXE}" croco.in
  fi
) 2>&1 | tee "${RUN_LOG}"

echo
echo "Run finalizado."
echo "Salida local   : ${RUN_DIR}/OUT"
echo "Snapshot config: ${SNAP}"
echo "Log            : ${RUN_LOG}"
