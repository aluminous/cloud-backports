#!/usr/bin/env bash
# Build Istio 1.10.6 pilot-discovery for linux/arm64 from the pinned inputs, verify it, and
# stage the image build context.
#
#   scripts/build-istio-pilot.sh [--engine docker|podman] [--modules-tar FILE]
#                                [--save-modules FILE] [--out DIR] [--platform linux/arm64]
#
#   --modules-tar FILE   build fully offline from a saved Go module set (no network at all
#                        in the compile container); its sha256 must equal MODULES_SHA256
#   --save-modules FILE  after an online build, save the module set (deterministic tar) to
#                        FILE and check it against MODULES_SHA256
#   --out DIR            default: out/istio-pilot-1.10.6
#   --platform P         platform of the toolchain container (default linux/arm64: native on
#                        an arm64 machine; linux/amd64 cross-compiles, unverified)
#
# Steps: download the source tarball (sha256-checked), compile in the pinned Go container
# with upstream's release flags, check the binary (AArch64 ELF, sha256 == BINARY_SHA256_ARM64,
# `pilot-discovery version` = 1.10.6 / upstream revision / Clean / go1.16.9), then write
# <out>/context/ for images/istio-pilot/1.10.6/Containerfile. Exits non-zero on any mismatch.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
INPUTS="$ROOT/images/istio-pilot/1.10.6/inputs.env"
# shellcheck source=../images/istio-pilot/1.10.6/inputs.env
source "$INPUTS"

ENGINE=""
MODULES_TAR=""
SAVE_MODULES=""
OUT="$ROOT/out/istio-pilot-$ISTIO_VERSION"
BUILD_PLATFORM="linux/arm64"
TARGET_ARCH="arm64"
while [ $# -gt 0 ]; do
  case "$1" in
    --engine) ENGINE=$2; shift 2 ;;
    --modules-tar) MODULES_TAR=$2; shift 2 ;;
    --save-modules) SAVE_MODULES=$2; shift 2 ;;
    --out) OUT=$2; shift 2 ;;
    --platform) BUILD_PLATFORM=$2; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$ENGINE" ]; then
  if command -v docker >/dev/null 2>&1; then ENGINE=docker; else ENGINE=podman; fi
fi

say() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}
# Go makes its module cache read-only; make it deletable first.
rm_tree() { [ -e "$1" ] && chmod -R u+w "$1" && rm -rf "$1" || true; }

CACHE="$ROOT/.cache"
WORK="$OUT/work"
mkdir -p "$CACHE" "$OUT"
START=$(date +%s)

# 1. source -----------------------------------------------------------------------------
SRC_TGZ="$CACHE/istio-$ISTIO_VERSION.tar.gz"
if [ ! -f "$SRC_TGZ" ] || [ "$(sha256_of "$SRC_TGZ")" != "$SOURCE_SHA256" ]; then
  say "downloading $SOURCE_URL"
  curl -fsSL --retry 3 -o "$SRC_TGZ.part" "$SOURCE_URL"
  mv "$SRC_TGZ.part" "$SRC_TGZ"
fi
got=$(sha256_of "$SRC_TGZ")
[ "$got" = "$SOURCE_SHA256" ] || die "source sha256 $got, pinned $SOURCE_SHA256"
say "source verified: sha256 $got"
rm_tree "$WORK"
mkdir -p "$WORK/gomod" "$WORK/bin"
tar -xzf "$SRC_TGZ" -C "$WORK"
SRC="$WORK/istio-$ISTIO_VERSION"
[ -f "$SRC/go.mod" ] || die "no go.mod in $SRC"

# 2. compile ----------------------------------------------------------------------------
LDFLAGS="-extldflags -static"
for kv in "buildVersion=$ISTIO_VERSION" "buildGitRevision=$ISTIO_REVISION" \
          "buildStatus=Clean" "buildTag=$ISTIO_VERSION" "buildHub=docker.io/istio"; do
  LDFLAGS="$LDFLAGS -X istio.io/pkg/version.$kv"
done
NET=()
PROXY="${GOPROXY_OVERRIDE:-$GOPROXY_DEFAULT}"
if [ -n "$MODULES_TAR" ]; then
  got=$(sha256_of "$MODULES_TAR")
  [ "$got" = "$MODULES_SHA256" ] || die "module set sha256 $got, pinned $MODULES_SHA256"
  tar -xf "$MODULES_TAR" -C "$WORK/gomod"
  NET=(--network none)
  PROXY=off
  say "compiling offline from the saved module set (no network)"
else
  say "compiling; Go modules from $PROXY, verified against the release's go.sum"
fi
"$ENGINE" run --rm --platform "$BUILD_PLATFORM" ${NET[@]+"${NET[@]}"} \
  -v "$SRC:/src:ro" -v "$WORK/gomod:/gomod" -v "$WORK/bin:/out" -w /src \
  -e GOMODCACHE=/gomod -e GOCACHE=/tmp/gocache -e GOFLAGS=-mod=readonly -e GOSUMDB=off \
  -e "GOPROXY=$PROXY" -e CGO_ENABLED=0 -e GOOS=linux -e "GOARCH=$TARGET_ARCH" \
  "$GO_BUILDER" \
  go build -trimpath -o /out/pilot-discovery -ldflags "$LDFLAGS" ./pilot/cmd/pilot-discovery
BIN="$WORK/bin/pilot-discovery"

if [ -n "$SAVE_MODULES" ]; then
  python3 "$ROOT/scripts/module_tar.py" write "$WORK/gomod/cache/download" "$SAVE_MODULES"
  got=$(sha256_of "$SAVE_MODULES")
  [ "$got" = "$MODULES_SHA256" ] || die "saved module set sha256 $got, pinned $MODULES_SHA256"
  say "module set saved and verified: $SAVE_MODULES"
fi

# 3. verify -----------------------------------------------------------------------------
python3 - "$BIN" <<'PY'
import sys
h = open(sys.argv[1], "rb").read(20)
if h[:4] != b"\x7fELF":
    sys.exit("not an ELF binary")
machine = int.from_bytes(h[18:20], "little" if h[5] == 1 else "big")
if machine != 183:
    sys.exit(f"ELF machine {machine}, expected AArch64 (183)")
PY
got=$(sha256_of "$BIN")
[ "$got" = "$BINARY_SHA256_ARM64" ] || die "binary sha256 $got, pinned $BINARY_SHA256_ARM64 (not reproducible here: report it)"
say "binary verified: sha256 $got"
VERSION_JSON=$("$ENGINE" run --rm --platform linux/arm64 --network none -v "$WORK/bin:/out:ro" \
  "$GO_BUILDER" /out/pilot-discovery version -o json)
python3 - "$ISTIO_VERSION" "$ISTIO_REVISION" "$GO_VERSION" "$VERSION_JSON" <<'PY'
import json, sys
version, revision, golang, out = sys.argv[1:]
v = json.loads(out)["clientVersion"]
want = {"version": version, "revision": revision, "status": "Clean", "golang_version": golang}
bad = {k: (v.get(k), w) for k, w in want.items() if v.get(k) != w}
if bad:
    sys.exit(f"pilot-discovery version mismatch (got, want): {bad}")
print(f"==> version verified: {v['version']} {v['revision']} {v['status']} {v['golang_version']}")
PY

# 4. build context ----------------------------------------------------------------------
CTX="$OUT/context"
rm -rf "$CTX"
mkdir -p "$CTX"
cp "$BIN" "$CTX/pilot-discovery"
chmod 0755 "$CTX/pilot-discovery"
cp "$SRC/LICENSE" "$CTX/LICENSE"
cp -R "$SRC/licenses" "$CTX/licenses"
cp "$ROOT/images/istio-pilot/1.10.6/NOTICE" "$CTX/NOTICE"
cat > "$CTX/BUILD-METADATA.json" <<JSON
{
  "component": "istio/pilot-discovery",
  "version": "$ISTIO_VERSION",
  "upstream_revision": "$ISTIO_REVISION",
  "source_url": "$SOURCE_URL",
  "source_sha256": "$SOURCE_SHA256",
  "go_builder": "$GO_BUILDER",
  "go_version": "$GO_VERSION",
  "go_modules_sha256": "$MODULES_SHA256",
  "binary_sha256": "$BINARY_SHA256_ARM64",
  "ldflags": "$LDFLAGS",
  "target": "linux/arm64",
  "fidelity": "unmodified upstream source; pilot control plane only (istiod), no proxyv2"
}
JSON
rm_tree "$WORK/gomod"
rm_tree "$SRC"
say "build context: $CTX ($(( $(date +%s) - START )) s)"
say "next: $ENGINE build --platform linux/arm64 -f images/istio-pilot/1.10.6/Containerfile \\"
say "      --build-arg BASE_IMAGE=$BASE_IMAGE ... $CTX   (or scripts/image-build.sh)"
