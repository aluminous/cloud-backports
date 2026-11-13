#!/usr/bin/env bash
# Publish the multi-arch tag: linux/arm64 = this repository's build (by digest), linux/amd64 =
# upstream's official image (by digest, copied as is, never rebuilt).
#   scripts/assemble-index.sh ARM64_DIGEST
# Needs `docker buildx` and a login to the target registry. Prints the index digest.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
source "$ROOT/registry.env"
source "$ROOT/images/istio-pilot/1.10.6/inputs.env"
NS="${IMAGE_NAMESPACE_OVERRIDE:-$IMAGE_NAMESPACE}"
ARM64_DIGEST=${1:?usage: assemble-index.sh ARM64_DIGEST}
REPO="$NS/istio-pilot"
docker buildx imagetools create \
  --tag "$REPO:$ISTIO_VERSION" \
  --annotation "index:org.opencontainers.image.version=$ISTIO_VERSION" \
  --annotation "index:org.opencontainers.image.licenses=Apache-2.0" \
  --annotation "index:dev.cloud-backports.upstream.revision=$ISTIO_REVISION" \
  "$REPO@$ARM64_DIGEST" \
  "$UPSTREAM_IMAGE@$UPSTREAM_AMD64_DIGEST" >&2
RAW=$(docker buildx imagetools inspect --raw "$REPO:$ISTIO_VERSION")
python3 - "$RAW" "$ARM64_DIGEST" "$UPSTREAM_AMD64_DIGEST" <<'PY' >&2
import json, sys
idx, arm, amd = json.loads(sys.argv[1]), sys.argv[2], sys.argv[3]
got = {f"{m['platform']['os']}/{m['platform']['architecture']}": m["digest"]
       for m in idx["manifests"] if m.get("platform", {}).get("os") != "unknown"}
want = {"linux/arm64": arm, "linux/amd64": amd}
if got != want:
    sys.exit(f"index platforms {got}, expected {want}")
print(f"index ok: {got}")
PY
docker buildx imagetools inspect --format '{{.Manifest.Digest}}' "$REPO:$ISTIO_VERSION"
