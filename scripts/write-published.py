#!/usr/bin/env python3
"""Record what a release published, for consumers to pin (published.yaml).

    write-published.py --namespace NS --index-digest D --arm64-digest D [--run-url URL]
                       [--source-revision SHA] [--out published.yaml]

Reads images/istio-pilot/1.10.6/inputs.env for the pins. Replaces the `istio-pilot 1.10.6`
entry in the output file and keeps the others. Standard library only (no YAML parser: the
file is written in a fixed, simple shape).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inputs() -> dict[str, str]:
    out = {}
    for line in (ROOT / "images/istio-pilot/1.10.6/inputs.env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def entry(a: argparse.Namespace, pins: dict[str, str]) -> list[str]:
    q = json.dumps  # YAML accepts JSON strings
    return [
        f"  - name: istio-pilot",
        f"    tag: {q(pins['ISTIO_VERSION'])}",
        f"    reference: {q(a.namespace + '/istio-pilot:' + pins['ISTIO_VERSION'])}",
        f"    index_digest: {q(a.index_digest)}",
        f"    pinned: {q(a.namespace + '/istio-pilot:' + pins['ISTIO_VERSION'] + '@' + a.index_digest)}",
        "    platforms:",
        f"      linux/arm64: {{digest: {q(a.arm64_digest)}, origin: built here, "
        f"binary_sha256: {q(pins['BINARY_SHA256_ARM64'])}}}",
        f"      linux/amd64: {{digest: {q(pins['UPSTREAM_AMD64_DIGEST'])}, origin: "
        f"{q('carried over from ' + pins['UPSTREAM_IMAGE'])}}}",
        f"    upstream_revision: {q(pins['ISTIO_REVISION'])}",
        f"    source_revision: {q(a.source_revision or '')}",
        f"    run: {q(a.run_url or '')}",
        f"    published: {q(dt.datetime.now(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'))}",
    ]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--namespace", required=True)
    p.add_argument("--index-digest", required=True)
    p.add_argument("--arm64-digest", required=True)
    p.add_argument("--run-url")
    p.add_argument("--source-revision")
    p.add_argument("--out", type=Path, default=ROOT / "published.yaml")
    a = p.parse_args()
    for d in (a.index_digest, a.arm64_digest):
        if not (d.startswith("sha256:") and len(d) == 71):
            raise SystemExit(f"not a sha256 digest: {d}")
    pins = inputs()
    header = ["# Published images, by digest (written by scripts/write-published.py).",
              "# Pin the `pinned` reference (or a platform digest), never the tag alone.",
              "images:"]
    kept: list[list[str]] = []
    if a.out.is_file():  # keep other entries (blocks starting with "  - name:")
        block: list[str] = []
        for line in a.out.read_text().splitlines():
            if line.startswith("  - name:"):
                if block:
                    kept.append(block)
                block = [line]
            elif block:
                block.append(line)
        if block:
            kept.append(block)
    me = entry(a, pins)
    kept = [b for b in kept if not (b[0] == me[0] and me[1] in b)]
    lines = header + [l for b in kept for l in b] + me
    a.out.write_text("\n".join(lines) + "\n")
    print(a.out.read_text())


if __name__ == "__main__":
    main()
