#!/bin/bash
######################################################
##
## CROCO EXPERIMENT BUILDER, Universidad Nacional de
##                           Tierra del Fuego,
##                           Ushuaia, ARGENTINA
##
## Enero 2026
##
## Daniel Badagnani,               Monica Manceñido
## dbadagnani@untdf.edu.ar         yavamoni@gmail.com
##
#######################################################

# Root del árbol CROCO_EXPERIMENTS (donde está este setup.sh)
export CROCOEXP_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Versión de distro CROCO dentro del root (intocable)
export version="croco-v2.1.2"

# Base donde viven los experimentos (nombre canónico del builder)
export CROCOEXP_EXPERIMENTS_DIR="${CROCOEXP_HOME}/experiments"

# Alias por compatibilidad (si querés mantenerlo un tiempo)
export MSOT_EXPERIMENTS_DIR="${CROCOEXP_EXPERIMENTS_DIR}"

echo "CROCOEXP root      : ${CROCOEXP_HOME}"
echo "CROCO version      : ${version}"
echo "Experiments        : ${CROCOEXP_EXPERIMENTS_DIR}"

