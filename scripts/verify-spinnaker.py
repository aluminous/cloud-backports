#!/usr/bin/env python3
"""Verify pushed Spinnaker 1.25.4 images against the pins, using only the registry API.

    verify-spinnaker.py [--namespace NS] [--only SERVICE]... [--insecure] [--auth-file FILE]
                        [--blobs]

For each pinned image: the manifest fetched by its pinned digest and by tag hashes to the
pinned manifest digest; it names the pinned config digest; the config blob fetched from the
registry hashes to that digest and has the pinned number of diff_ids; the manifest's layers
are exactly those diff_ids (layers are pushed uncompressed). With --blobs every layer is also
downloaded and hashed (the full size of the image). Exits non-zero on any mismatch.
Credentials as for push-spinnaker.py (needed only for a private package). Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spinnaker_archive as sa  # noqa: E402


def verify(reg: sa.Registry, repo: str, pin: sa.Pin, blobs: bool) -> None:
    by_digest, _ = reg.get_manifest(repo, pin.manifest_digest)
    by_tag, _ = reg.get_manifest(repo, pin.version)
    for what, data in (("by digest", by_digest), ("by tag", by_tag)):
        if sa.digest_of(data) != pin.manifest_digest:
            raise sa.Error(f"{pin.service}: manifest {what} hashes to {sa.digest_of(data)}, "
                           f"pinned {pin.manifest_digest}")
    m = json.loads(by_digest)
    if m.get("mediaType") != sa.MANIFEST_TYPE or m.get("schemaVersion") != 2:
        raise sa.Error(f"{pin.service}: unexpected manifest type {m.get('mediaType')}")
    if m["config"]["digest"] != pin.config_digest:
        raise sa.Error(f"{pin.service}: manifest config {m['config']['digest']}, "
                       f"pinned {pin.config_digest}")
    config = reg.get_blob(repo, pin.config_digest)
    if sa.digest_of(config) != pin.config_digest or len(config) != m["config"]["size"]:
        raise sa.Error(f"{pin.service}: config blob does not match {pin.config_digest}")
    c = json.loads(config)
    diff_ids = c["rootfs"]["diff_ids"]
    if len(diff_ids) != pin.layers or [l["digest"] for l in m["layers"]] != diff_ids:
        raise sa.Error(f"{pin.service}: layers {[l['digest'][7:19] for l in m['layers']]} "
                       f"are not the {pin.layers} pinned diff_ids")
    if (c["os"], c["architecture"]) != ("linux", "amd64"):
        raise sa.Error(f"{pin.service}: image is {c['os']}/{c['architecture']}")
    if blobs:
        for l in m["layers"]:
            h = hashlib.sha256(reg.get_blob(repo, l["digest"])).hexdigest()
            if "sha256:" + h != l["digest"]:
                raise sa.Error(f"{pin.service}: layer {l['digest']} downloads as sha256:{h}")
    print(f"ok  {pin.service:<11} {pin.version}  manifest {pin.manifest_digest[:19]}…  "
          f"image ID {pin.config_digest[:19]}…  {pin.layers} layers"
          f"{'  (layer bytes checked)' if blobs else ''}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--namespace")
    p.add_argument("--only", action="append")
    p.add_argument("--insecure", action="store_true", help="plain http (local registry)")
    p.add_argument("--auth-file")
    p.add_argument("--blobs", action="store_true", help="also download and hash every layer")
    a = p.parse_args()
    _, pins = sa.load_pins(a.only)
    ns = sa.namespace(a.namespace)
    host, _, base = ns.partition("/")
    reg = sa.Registry(host, a.insecure, a.auth_file)
    for pin in pins:
        verify(reg, f"{base}/{pin.repo_name}", pin, a.blobs)
    print(f"==> {len(pins)} image(s) verified against images/spinnaker/{sa.RELEASE}/inputs.env")


if __name__ == "__main__":
    try:
        main()
    except sa.Error as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
