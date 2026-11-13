#!/usr/bin/env bash
# Build the istio-pilot 1.10.6 arm64 image from the context staged by build-istio-pilot.sh.
#   scripts/image-build.sh [--engine docker|podman] [--tag REF] [--context DIR]
# Default tag: $IMAGE_NAMESPACE/istio-pilot:1.10.6-arm64 (registry.env).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
source "$ROOT/registry.env"
source "$ROOT/images/istio-pilot/1.10.6/inputs.env"
ENGINE=""; TAG="${IMAGE_NAMESPACE}/istio-pilot:${ISTIO_VERSION}-arm64"
CTX="$ROOT/out/istio-pilot-$ISTIO_VERSION/context"
while [ $# -gt 0 ]; do
  case "$1" in
    --engine) ENGINE=$2; shift 2 ;; --tag) TAG=$2; shift 2 ;; --context) CTX=$2; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$ENGINE" ] || { command -v docker >/dev/null 2>&1 && ENGINE=docker || ENGINE=podman; }
[ -f "$CTX/pilot-discovery" ] || { echo "no $CTX/pilot-discovery: run scripts/build-istio-pilot.sh" >&2; exit 1; }
"$ENGINE" build --platform linux/arm64 -f "$ROOT/images/istio-pilot/1.10.6/Containerfile" \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" --build-arg "ISTIO_VERSION=$ISTIO_VERSION" \
  --build-arg "ISTIO_REVISION=$ISTIO_REVISION" --build-arg "SOURCE_URL=$SOURCE_URL" \
  --build-arg "SOURCE_SHA256=$SOURCE_SHA256" --build-arg "BINARY_SHA256=$BINARY_SHA256_ARM64" \
  --label "org.opencontainers.image.revision=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)" \
  -t "$TAG" "$CTX"
echo "built $TAG"
