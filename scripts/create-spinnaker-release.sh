#!/usr/bin/env bash
# Create a DRAFT GitHub release holding the Spinnaker archive assets: the five image archives
# and the source bundle. Publishing the draft (in the GitHub UI) creates the tag
# spinnaker-1.25.4 and so starts .github/workflows/spinnaker-archive.yml.
#
#   scripts/create-spinnaker-release.sh --archive-dir DIR --sources-tar FILE [--tag TAG] [--run]
#
# Without --run it only checks every file against the pins and prints what it would do.
# With --run it needs `gh` logged in as a user who can create releases (gh auth login; nothing
# is read from the command line) and uploads the files one at a time (a file is at most 2 GiB).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=/dev/null
source "$ROOT/images/spinnaker/1.25.4/inputs.env"
TAG=spinnaker-1.25.4; RUN=0; ARCHIVES=""; SOURCES=""
REPO=${GITHUB_REPOSITORY:-aluminous/cloud-backports}
while [ $# -gt 0 ]; do
  case "$1" in
    --archive-dir) ARCHIVES=$2; shift 2 ;; --sources-tar) SOURCES=$2; shift 2 ;;
    --tag) TAG=$2; shift 2 ;; --run) RUN=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$ARCHIVES" ] && [ -n "$SOURCES" ] || { echo "usage: $0 --archive-dir DIR --sources-tar FILE [--tag TAG] [--run]" >&2; exit 2; }
case "$TAG" in spinnaker-1.25.4*) ;; *) echo "tag must match spinnaker-1.25.4*" >&2; exit 2 ;; esac
sha256_of() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

FILES=()
for s in $SERVICES; do
  a=$(echo "$s" | tr a-z- A-Z_)_ARCHIVE; h=$(echo "$s" | tr a-z- A-Z_)_ARCHIVE_SHA256
  [ -n "${!a:-}" ] || continue
  f="$ARCHIVES/${!a}"
  [ -f "$f" ] || { echo "error: missing $f" >&2; exit 1; }
  got=$(sha256_of "$f")
  [ "$got" = "${!h}" ] || { echo "error: $f sha256 $got, pinned ${!h}" >&2; exit 1; }
  FILES+=("$f")
done
[ "$(basename "$SOURCES")" = "$SOURCES_BUNDLE" ] || { echo "error: the source bundle must be named $SOURCES_BUNDLE" >&2; exit 1; }
got=$(sha256_of "$SOURCES"); [ "$got" = "$SOURCES_BUNDLE_SHA256" ] || { echo "error: $SOURCES sha256 $got, pinned $SOURCES_BUNDLE_SHA256" >&2; exit 1; }
FILES+=("$SOURCES")
for f in "${FILES[@]}"; do
  size=$(wc -c < "$f"); [ "$size" -lt 2147483648 ] || { echo "error: $f is $size bytes, over the 2 GiB asset limit" >&2; exit 1; }
done
echo "==> ${#FILES[@]} files match the pins"

NOTES="Archived Spinnaker 1.25.4 service images (see images/spinnaker/1.25.4/NOTICE) and the corresponding source of their GPL/LGPL-licensed packages ($SOURCES_BUNDLE). Publishing this release runs the spinnaker-archive workflow, which pushes the images to GHCR."
if [ "$RUN" != 1 ]; then
  echo "would run: gh release create $TAG --repo $REPO --draft --title \"Spinnaker 1.25.4 archive\" --notes ..."
  for f in "${FILES[@]}"; do echo "would run: gh release upload $TAG --repo $REPO \"$f\""; done
  exit 0
fi
gh release create "$TAG" --repo "$REPO" --draft --title "Spinnaker 1.25.4 archive" --notes "$NOTES"
for f in "${FILES[@]}"; do
  echo "==> uploading $(basename "$f")"
  gh release upload "$TAG" --repo "$REPO" "$f"
done
echo "==> draft release $TAG created; check the assets, then publish it in the GitHub UI"
