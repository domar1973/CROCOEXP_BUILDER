#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXP_HOST_DIR="${ROOT_DIR}/CROCO_EXPERIMENTS"
EXP_CONT_DIR="/opt/CROCO_EXPERIMENTS"
CROCO_IMAGE="domarcroco/images-for-croco:base_croco_msot-1.0.0"

if [[ ! -d "${EXP_HOST_DIR}" ]]; then
  echo "ERROR: no existe el directorio del experimento en el host: ${EXP_HOST_DIR}"
  exit 1
fi

echo
echo "== Ejecutando contenedor CROCO =="
echo "Imagen         : ${CROCO_IMAGE}"
echo "Host mount     : ${EXP_HOST_DIR}"
echo "Container mount: ${EXP_CONT_DIR}"
echo

exec docker run -it --rm \
  -v "${EXP_HOST_DIR}:${EXP_CONT_DIR}" \
  -w "${EXP_CONT_DIR}" \
  "${CROCO_IMAGE}" \
  /bin/bash
