#!/usr/bin/env python3
"""Record what a Spinnaker archive release published, for consumers to pin (published.yaml).

    write-published-spinnaker.py --result push.json [--run-url URL] [--source-revision SHA]
                                 [--out published.yaml]

`push.json` is the `--result` file of scripts/push-spinnaker.py. Every digest in it must equal
the pin in images/spinnaker/1.25.4/inputs.env. Replaces the `spinnaker-<service>` entries in the
output file and keeps all others (the istio-pilot entry, written by write-published.py).
Standard library only (the YAML is written in a fixed, simple shape).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spinnaker_archive as sa  # noqa: E402

q = json.dumps  # YAML accepts JSON strings


def entry(r: dict, pin: sa.Pin, a: argparse.Namespace, now: str) -> list[str]:
    return [
        f"  - name: {pin.repo_name}",
        f"    tag: {q(pin.version)}",
        f"    reference: {q(r['reference'])}",
        f"    digest: {q(r['digest'])}",
        f"    pinned: {q(r['reference'] + '@' + r['digest'])}",
        f"    config_digest: {q(pin.config_digest)}",
        "    platform: linux/amd64",
        f"    origin: {q(pin.origin)}",
        f"    original_reference: {q(pin.original)}",
        f"    archive_sha256: {q(pin.archive_sha256)}",
        f"    source_revision: {q(a.source_revision or '')}",
        f"    run: {q(a.run_url or '')}",
        f"    published: {q(now)}",
    ]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--result", required=True, type=Path)
    p.add_argument("--run-url")
    p.add_argument("--source-revision")
    p.add_argument("--out", type=Path, default=sa.ROOT / "published.yaml")
    a = p.parse_args()
    _, pins = sa.load_pins()
    by_service = {p.service: p for p in pins}
    results = json.loads(a.result.read_text())
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    new: list[list[str]] = []
    for r in results:
        pin = by_service[r["service"]]
        if r["digest"] != pin.manifest_digest:
            raise SystemExit(f"{pin.service}: pushed digest {r['digest']}, pinned {pin.manifest_digest}")
        new.append(entry(r, pin, a, now))
    names = {b[0] for b in new}
    kept: list[list[str]] = []
    if a.out.is_file():
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
    kept = [b for b in kept if b[0] not in names]
    header = ["# Published images, by digest (written by scripts/write-published*.py).",
              "# Pin the `pinned` reference (or a platform digest), never the tag alone.",
              "images:"]
    a.out.write_text("\n".join(header + [l for b in kept + new for l in b]) + "\n")
    print(a.out.read_text())


if __name__ == "__main__":
    main()
