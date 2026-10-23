#!/bin/bash
# Build Deck-8 firmware locally (after setup_toolchain.sh). Output: ../out/deck8.uf2 (and .hex for SWD).
#   tools/build.sh           incremental build
#   tools/build.sh pristine  clean rebuild
set -euo pipefail
FW="$(cd "$(dirname "$0")/.." && pwd)"
TOP="$HOME/zmk-build"
export PATH="$TOP/venv/bin:$TOP/bin:$PATH"
export ZEPHYR_TOOLCHAIN_VARIANT=zephyr
export ZEPHYR_SDK_INSTALL_DIR="$TOP/zephyr-sdk-0.17.4"
cmp -s "$FW/config/west.yml" "$TOP/ws/config/west.yml" || {
  cp "$FW/config/west.yml" "$TOP/ws/config/west.yml"; (cd "$TOP/ws" && west update --narrow -o=--depth=1); }
cd "$TOP/ws"
west build ${1:+-p always} -s zmk/app -d build/deck8 -b deck8//zmk -S studio-rpc-usb-uart -- \
  -DZMK_CONFIG="$FW/config" -DZMK_EXTRA_MODULES="$FW" -DEXTRA_CONF_FILE="$FW/tools/local-sdk.conf"
mkdir -p "$FW/out"
cp build/deck8/zephyr/zmk.uf2 "$FW/out/deck8.uf2"
cp build/deck8/zephyr/zmk.hex "$FW/out/deck8.hex"
ls -l "$FW/out"
