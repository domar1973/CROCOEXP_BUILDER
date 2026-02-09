#!/bin/bash
# Este script crea la imagen con todos los prerequisitos 
# para compilar y ejecutar los experimentos CROCO.
#
# Daniel Badagnani, Ushuaia, enero 2026
#

set -euo pipefail

# ------------------------------------------------------------
# deploy.sh - CROCO_EXPERIMENTS
#
# - Verifica prerequisitos (docker)
# - Pull de la imagen base
# - Genera run.sh canónico (mount de CROCO_EXPERIMENTS)
# ------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR}"                 # asumimos que deploy.sh está en el root del repo/proyecto
EXP_DIR_NAME="CROCO_EXPERIMENTS"
EXP_HOST_DIR="${ROOT_DIR}/${EXP_DIR_NAME}"
EXP_CONT_DIR="/opt/${EXP_DIR_NAME}"

# Imagen por defecto (se puede overridear con env var CROCO_IMAGE)
DEFAULT_IMAGE="domarcroco/images-for-croco:base_croco_msot-1.0.0"
CROCO_IMAGE="${CROCO_IMAGE:-$DEFAULT_IMAGE}"

RUN_SH="${ROOT_DIR}/run.sh"

usage() {
  cat <<EOF
Uso:
  ./deploy.sh [--image <docker_image>] [--no-pull]

Opciones:
  --image <docker_image>  Imagen a usar (default: ${DEFAULT_IMAGE})
  --no-pull               No hace docker pull (asume imagen ya disponible)
  -h, --help              Muestra ayuda

Variables de entorno:
  CROCO_IMAGE             Alternativa a --image

Efectos:
  - Verifica que exista ${EXP_DIR_NAME}/ (la crea si no existe)
  - Genera run.sh que monta:
      ${EXP_HOST_DIR}  ->  ${EXP_CONT_DIR}
EOF
}

DO_PULL=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --image)
      CROCO_IMAGE="$2"
      shift 2
      ;;
    --no-pull)
      DO_PULL=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: argumento desconocido: $1"
      echo
      usage
      exit 1
      ;;
  esac
done

echo
echo "== Deploy CROCO_EXPERIMENTS =="
echo "ROOT_DIR     : ${ROOT_DIR}"
echo "EXP_HOST_DIR : ${EXP_HOST_DIR}"
echo "EXP_CONT_DIR : ${EXP_CONT_DIR}"
echo "CROCO_IMAGE  : ${CROCO_IMAGE}"
echo

# Prerequisitos
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker no está instalado o no está en PATH."
  exit 1
fi

# Asegurar estructura local del experimento
if [[ ! -d "${EXP_HOST_DIR}" ]]; then
  echo "No existe ${EXP_DIR_NAME}/. Creándola en: ${EXP_HOST_DIR}"
  mkdir -p "${EXP_HOST_DIR}"
fi

# Pull de imagen (opcional)
if [[ "${DO_PULL}" -eq 1 ]]; then
  echo "Descargando imagen Docker (pull): ${CROCO_IMAGE}"
  docker pull "${CROCO_IMAGE}"
else
  echo "Salteando docker pull (--no-pull)."
fi

# Generar run.sh canónico
cat > "${RUN_SH}" <<EOF
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
EXP_HOST_DIR="\${ROOT_DIR}/${EXP_DIR_NAME}"
EXP_CONT_DIR="${EXP_CONT_DIR}"
CROCO_IMAGE="${CROCO_IMAGE}"

if [[ ! -d "\${EXP_HOST_DIR}" ]]; then
  echo "ERROR: no existe el directorio del experimento en el host: \${EXP_HOST_DIR}"
  exit 1
fi

echo
echo "== Ejecutando contenedor CROCO =="
echo "Imagen         : \${CROCO_IMAGE}"
echo "Host mount     : \${EXP_HOST_DIR}"
echo "Container mount: \${EXP_CONT_DIR}"
echo

exec docker run -it --rm \\
  -u "$(id -u):$(id -g)" \\
  -e HOME="/tmp" \\
  -v "\${EXP_HOST_DIR}:\${EXP_CONT_DIR}" \\
  -w "\${EXP_CONT_DIR}" \\
  "\${CROCO_IMAGE}" \\
  /bin/bash
EOF

chmod +x "${RUN_SH}"

echo
echo "OK:"
echo " - Imagen lista: ${CROCO_IMAGE}"
echo " - Script generado: ${RUN_SH}"
echo
echo "Siguiente paso:"
echo "  ./run.sh"
echo
