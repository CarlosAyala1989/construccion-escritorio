#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

STAGING_DIR="${PROJECT_ROOT}/build/windows-online-installer"
NSIS_ROOT="${PROJECT_ROOT}/build/nsis-root"
NSIS_DEBS="${PROJECT_ROOT}/build/nsis-debs"
OUT_FILE="${PROJECT_ROOT}/dist/windows/GobernanzaDocumentalSetup-actualizado.exe"
LEGACY_OUT_FILE="${PROJECT_ROOT}/dist/windows/GobernanzaDocumentalSetup.exe"

rm -rf "${STAGING_DIR}"
mkdir -p "${STAGING_DIR}/app" "${STAGING_DIR}/installer" "${PROJECT_ROOT}/dist/windows"

python3 scripts/prepare-installer-env.py

cp main.py requirements.txt "${STAGING_DIR}/app/"
cp -R src web "${STAGING_DIR}/app/"
mkdir -p "${STAGING_DIR}/app/data/templates"
if [ -d data/templates ]; then
    find data/templates -mindepth 1 -maxdepth 1 -exec cp -R {} "${STAGING_DIR}/app/data/templates/" \;
fi

find "${STAGING_DIR}/app" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${STAGING_DIR}/app" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

cp installer/bootstrap-windows.ps1 "${STAGING_DIR}/installer/"
cp installer/.env "${STAGING_DIR}/installer/app.env"

if command -v makensis >/dev/null 2>&1; then
    MAKENSIS="$(command -v makensis)"
else
    MAKENSIS="${NSIS_ROOT}/usr/bin/makensis"
    if [ ! -x "${MAKENSIS}" ]; then
        mkdir -p "${NSIS_DEBS}" "${NSIS_ROOT}"
        (
            cd "${NSIS_DEBS}"
            apt-get download nsis nsis-common
        )
        for deb in "${NSIS_DEBS}"/*.deb; do
            dpkg-deb -x "${deb}" "${NSIS_ROOT}"
        done
    fi
    export NSISDIR="${NSIS_ROOT}/usr/share/nsis"
fi

"${MAKENSIS}" \
    -V2 \
    -DOUT_FILE="${STAGING_DIR}/GobernanzaDocumental.exe" \
    installer/windows-launcher.nsi

"${MAKENSIS}" \
    -V2 \
    -DOUT_FILE="${OUT_FILE}" \
    -DSTAGING_DIR="${STAGING_DIR}" \
    installer/windows-online-installer.nsi

cp "${OUT_FILE}" "${LEGACY_OUT_FILE}"

printf '\nInstaladores generados:\n%s\n%s\n' "${OUT_FILE}" "${LEGACY_OUT_FILE}"
