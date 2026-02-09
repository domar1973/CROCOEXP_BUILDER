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

EXP_NAME="${1:-}"
if [[ -z "${EXP_NAME}" ]]; then
  echo "Uso: $0 <NOMBRE_EXPERIMENTO>"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${ROOT_DIR}/setup.sh"

# Resolver experiments dir (nombre canónico + compatibilidad con setup viejo)
if [[ -z "${CROCOEXP_EXPERIMENTS_DIR:-}" ]]; then
  if [[ -n "${MSOT_EXPERIMENTS_DIR:-}" ]]; then
    CROCOEXP_EXPERIMENTS_DIR="${MSOT_EXPERIMENTS_DIR}"
  else
    CROCOEXP_EXPERIMENTS_DIR="${CROCOEXP_HOME}/experiments"
  fi
fi

: "${CROCOEXP_HOME:?setup.sh no definió CROCOEXP_HOME}"
: "${version:?setup.sh no definió version}"

EXP_DIR="${CROCOEXP_EXPERIMENTS_DIR}/${EXP_NAME}"
EXP_OVR="${EXP_DIR}/EXP"
BUILD_DIR="${EXP_DIR}/build"
LOG_DIR="${EXP_DIR}/LOG"

if [[ ! -d "${EXP_DIR}" ]]; then
  echo "ERROR: no existe el experimento: ${EXP_DIR}"
  (cd "${CROCOEXP_EXPERIMENTS_DIR}" && ls -1) || true
  exit 1
fi
if [[ ! -d "${EXP_OVR}" ]]; then
  echo "ERROR: falta carpeta EXP/: ${EXP_OVR}"
  exit 1
fi

CROCO_ROOT="${CROCOEXP_HOME}/${version}"
CROCO_OCEAN="${CROCO_ROOT}/OCEAN"
JOB_OFFICIAL="${CROCO_OCEAN}/jobcomp"

if [[ ! -d "${CROCO_OCEAN}" ]]; then
  echo "ERROR: no existe OCEAN en la distro: ${CROCO_OCEAN}"
  exit 1
fi
if [[ ! -f "${JOB_OFFICIAL}" ]]; then
  echo "ERROR: no encuentro jobcomp oficial en: ${JOB_OFFICIAL}"
  exit 1
fi

mkdir -p "${BUILD_DIR}" "${LOG_DIR}"

# 1) Symlink "croco" para satisfacer SOURCE1=../croco/OCEAN (jobcomp oficial)
LINK_CROCO="${EXP_DIR}/croco"
if [[ -L "${LINK_CROCO}" ]]; then
  if [[ "$(readlink -f "${LINK_CROCO}")" != "$(readlink -f "${CROCO_ROOT}")" ]]; then
    rm -f "${LINK_CROCO}"
    ln -s "${CROCO_ROOT}" "${LINK_CROCO}"
  fi
elif [[ -e "${LINK_CROCO}" ]]; then
  echo "ERROR: existe ${LINK_CROCO} pero no es symlink. Necesito crear croco -> ${CROCO_ROOT}"
  exit 1
else
  ln -s "${CROCO_ROOT}" "${LINK_CROCO}"
fi

# 2) Stage overrides del experimento en build/ (RUNDIR del jobcomp)
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "${EXP_OVR}/" "${BUILD_DIR}/"
else
  rm -rf "${BUILD_DIR:?}/"* 2>/dev/null || true
  cp -a "${EXP_OVR}/." "${BUILD_DIR}/"
fi

# 3) Copiar jobcomp oficial a build/
cp -f "${JOB_OFFICIAL}" "${BUILD_DIR}/jobcomp"
chmod +x "${BUILD_DIR}/jobcomp"

# ---------------------------------------------------------
# ENV WRAP estilo TdF_MSOT (NetCDF + Compiler coherente)
# ---------------------------------------------------------

# NetCDF hardcodeado (como tu TdF_MSOT) - solo si no viene provisto ya
export CROCO_NETCDFLIB="${CROCO_NETCDFLIB:--L/opt/intel/netcdf/lib -L/opt/intel/netcdff/lib -lnetcdff -lnetcdf}"
export CROCO_NETCDFINC="${CROCO_NETCDFINC:--I/opt/intel/netcdf/include -I/opt/intel/netcdff/include}"

# Validación: evitar el caso tóxico "CROCO_NETCDFINC=-I"
if [[ "${CROCO_NETCDFINC}" =~ ^-I[[:space:]]*$ ]]; then
  echo "ERROR: CROCO_NETCDFINC quedó como '-I' vacío. Seteá ruta real de includes NetCDF."
  exit 1
fi

# Elegir compilador: si existe ifort, usamos Intel; si no, gfortran
# (Podés forzar exportando CROCO_CFT1 y CROCO_FFLAGS1 desde afuera)
if [[ -z "${CROCO_CFT1:-}" ]]; then
  if command -v ifort >/dev/null 2>&1; then
    export CROCO_CFT1="ifort"
    # Flags Intel coherentes (tomados de tu TdF_MSOT; podés ajustarlos)
    export CROCO_FFLAGS1="${CROCO_FFLAGS1:--O3 -fno-alias -i4 -r8 -fp-model precise}"
  else
    export CROCO_CFT1="gfortran"
    export CROCO_FFLAGS1="${CROCO_FFLAGS1:--O3 -fdefault-real-8 -fdefault-double-8 -std=legacy}"
  fi
fi

# Parchear jobcomp copiado para evitar llamadas a nf-config si no existe:
# (en tu caso no existe, y ensucia el output; además puede dejar NETCDFINC=-I vacío)
if ! command -v nf-config >/dev/null 2>&1; then
  # Reemplazamos las 2 líneas típicas por asignaciones seguras.
  # Esto NO toca la distro, solo la copia en build/.
  sed -i \
    -e 's|^NETCDFLIB=$(nf-config --flibs).*|NETCDFLIB="${CROCO_NETCDFLIB-$NETCDFLIB}"|g' \
    -e 's|^NETCDFINC=-I$(nf-config --includedir).*|NETCDFINC="${CROCO_NETCDFINC-$NETCDFINC}"|g' \
    "${BUILD_DIR}/jobcomp" || true
fi

TS="$(date +%Y%m%d_%H%M%S)"
LOGFILE="${LOG_DIR}/compile_${EXP_NAME}_${TS}.log"

echo
echo "Compilando experimento : ${EXP_NAME}"
echo "Distro CROCO           : ${CROCO_ROOT}"
echo "Build dir (RUNDIR)     : ${BUILD_DIR}"
echo "Jobcomp                : ${BUILD_DIR}/jobcomp"
echo "CROCO_CFT1             : ${CROCO_CFT1}"
echo "CROCO_FFLAGS1          : ${CROCO_FFLAGS1}"
echo "CROCO_NETCDFINC        : ${CROCO_NETCDFINC}"
echo "CROCO_NETCDFLIB        : ${CROCO_NETCDFLIB}"
echo "Log                    : ${LOGFILE}"
echo

(
  cd "${BUILD_DIR}"
  ./jobcomp 2>&1 | tee "${LOGFILE}"
)

echo
echo "OK. Revisá binarios y Compile/ en: ${BUILD_DIR}"
echo "Log: ${LOGFILE}"
