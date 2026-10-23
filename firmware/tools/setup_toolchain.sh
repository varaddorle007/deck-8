#!/bin/bash
# One-time local ZMK toolchain in ~/zmk-build (nothing system-wide): uv + Python 3.12, west/cmake/ninja,
# Zephyr SDK 0.17.4 (ARM only) and a west workspace pinned by ../config/west.yml.
set -euo pipefail
FW="$(cd "$(dirname "$0")/.." && pwd)"
TOP="$HOME/zmk-build"
SDK_VER=0.17.4
UV_VER=0.13.5
mkdir -p "$TOP/dl" "$TOP/bin"
export PATH="$TOP/venv/bin:$TOP/bin:$PATH"
cd "$TOP/dl"

fetch() {
  if [ ! -f "$2" ]; then curl -fL --retry 3 -o "$2.part" "$1"; mv "$2.part" "$2"; fi
}

echo "== uv $UV_VER"
fetch "https://github.com/astral-sh/uv/releases/download/$UV_VER/uv-aarch64-apple-darwin.tar.gz" uv.tar.gz
fetch "https://github.com/astral-sh/uv/releases/download/$UV_VER/uv-aarch64-apple-darwin.tar.gz.sha256" uv.sha256
[ "$(awk '{print $1}' uv.sha256)" = "$(shasum -a 256 uv.tar.gz | awk '{print $1}')" ] || { echo "uv checksum mismatch"; exit 1; }
tar -xzf uv.tar.gz -C "$TOP/bin" --strip-components 1

echo "== Python 3.12 venv"
[ -x "$TOP/venv/bin/python" ] || UV_PYTHON_INSTALL_DIR="$TOP/python" "$TOP/bin/uv" venv --python 3.12 "$TOP/venv"
VIRTUAL_ENV="$TOP/venv" "$TOP/bin/uv" pip install --quiet west cmake ninja grpcio-tools
# ZMK Studio's protocol needs protoc; grpcio-tools ships one, reached through this shim
printf '#!/bin/sh\nexec "%s/venv/bin/python" -m grpc_tools.protoc "$@"\n' "$TOP" > "$TOP/bin/protoc"
chmod +x "$TOP/bin/protoc"

echo "== Zephyr SDK $SDK_VER"
B="https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v$SDK_VER"
fetch "$B/zephyr-sdk-${SDK_VER}_macos-aarch64_minimal.tar.xz" sdk.tar.xz
fetch "$B/toolchain_macos-aarch64_arm-zephyr-eabi.tar.xz" arm.tar.xz
fetch "$B/sha256.sum" sdk.sha256
for f in "zephyr-sdk-${SDK_VER}_macos-aarch64_minimal.tar.xz:sdk.tar.xz" "toolchain_macos-aarch64_arm-zephyr-eabi.tar.xz:arm.tar.xz"; do
  want=$(grep " ${f%%:*}\$" sdk.sha256 | awk '{print $1}'); got=$(shasum -a 256 "${f##*:}" | awk '{print $1}')
  [ "$want" = "$got" ] || { echo "checksum mismatch for ${f%%:*}"; exit 1; }
done
SDK="$TOP/zephyr-sdk-$SDK_VER"
[ -d "$SDK" ] || tar -xJf sdk.tar.xz -C "$TOP"
[ -d "$SDK/arm-zephyr-eabi" ] || tar -xJf arm.tar.xz -C "$SDK"
xattr -dr com.apple.quarantine "$SDK" 2>/dev/null || true
# no setup.sh: it wants wget just to register the SDK; build.sh sets ZEPHYR_SDK_INSTALL_DIR instead

echo "== west workspace"
mkdir -p "$TOP/ws/config"
cp "$FW/config/west.yml" "$TOP/ws/config/west.yml"
cd "$TOP/ws"
[ -d .west ] || west init -l config
west update --narrow -o=--depth=1
west zephyr-export
VIRTUAL_ENV="$TOP/venv" "$TOP/bin/uv" pip install --quiet -r zephyr/scripts/requirements-base.txt
echo "== done"
