#!/usr/bin/env bash
# Verify an istio-pilot 1.10.6 image against the pinned inputs (linux/arm64).
#   scripts/verify-image.sh [--engine docker|podman] [--pull] REF
# REF: a local tag or a registry reference (ideally by digest). Checks: the image config
# (user 1337:1337, entrypoint, working directory /), the binary's sha256 against
# BINARY_SHA256_ARM64, and `pilot-discovery version` (version, upstream revision, Clean, Go).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
source "$ROOT/images/istio-pilot/1.10.6/inputs.env"
ENGINE=""; PULL=0
while [ $# -gt 1 ]; do
  case "$1" in
    --engine) ENGINE=$2; shift 2 ;; --pull) PULL=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
REF=${1:?usage: verify-image.sh [--engine E] [--pull] REF}
[ -n "$ENGINE" ] || { command -v docker >/dev/null 2>&1 && ENGINE=docker || ENGINE=podman; }
sha256_of() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

[ "$PULL" = 1 ] && "$ENGINE" pull --platform linux/arm64 "$REF" >/dev/null
CONFIG=$("$ENGINE" image inspect --format '{{json .Config}}' "$REF")
python3 - "$CONFIG" <<'PY'
import json, sys
c = json.loads(sys.argv[1])
want = {"User": "1337:1337", "Entrypoint": ["/usr/local/bin/pilot-discovery"]}
bad = {k: (c.get(k), w) for k, w in want.items() if c.get(k) != w}
if c.get("WorkingDir") not in ("", "/", None):
    bad["WorkingDir"] = (c.get("WorkingDir"), "/")
if bad:
    sys.exit(f"image config differs (got, want): {bad}")
print("==> config verified: user 1337:1337, entrypoint /usr/local/bin/pilot-discovery, workdir /")
PY
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
CID=$("$ENGINE" create --platform linux/arm64 "$REF")
"$ENGINE" cp "$CID:/usr/local/bin/pilot-discovery" "$TMP/pilot-discovery" >/dev/null
"$ENGINE" cp "$CID:/usr/share/doc/istio-pilot/LICENSE" "$TMP/LICENSE" >/dev/null
"$ENGINE" rm "$CID" >/dev/null
got=$(sha256_of "$TMP/pilot-discovery")
[ "$got" = "$BINARY_SHA256_ARM64" ] || { echo "error: binary sha256 $got, pinned $BINARY_SHA256_ARM64" >&2; exit 1; }
echo "==> binary verified: sha256 $got (licence present)"
OUT=$("$ENGINE" run --rm --platform linux/arm64 --network none "$REF" version -o json)
python3 - "$ISTIO_VERSION" "$ISTIO_REVISION" "$GO_VERSION" "$OUT" <<'PY'
import json, sys
version, revision, golang, out = sys.argv[1:]
v = json.loads(out)["clientVersion"]
want = {"version": version, "revision": revision, "status": "Clean", "golang_version": golang}
bad = {k: (v.get(k), w) for k, w in want.items() if v.get(k) != w}
if bad:
    sys.exit(f"version mismatch (got, want): {bad}")
print(f"==> version verified: {v['version']} {v['revision']} {v['status']} {v['golang_version']}")
PY
