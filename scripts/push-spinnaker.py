#!/usr/bin/env python3
"""Verify the local Spinnaker 1.25.4 archives against the pins and push them to a registry.

    push-spinnaker.py --archive-dir DIR [--namespace NS] [--only SERVICE]... [--insecure]
                      [--auth-file FILE]
                      [--convert-only] [--result FILE.json]

Pushes <NS>/spinnaker-<service>:<version> for each pinned image, one image at a time:

  1. the archive file must have the pinned sha256, and its image config the pinned digest
     (the image ID) and layer count;
  2. every layer (an uncompressed tar) is hashed, and must equal its diff_id in the config;
  3. the OCI manifest built from the config and the layers (pushed as they are, uncompressed,
     so nothing depends on a compressor) must have the pinned manifest digest, or nothing is
     uploaded;
  4. blobs (layers, then the config as it is in the archive), then the manifest are uploaded;
     the registry must report the pinned manifest digest.

NS defaults to IMAGE_NAMESPACE in registry.env. The archive directory is the one holding the
files named in the pins (the old test harness's bundle-cache `images/` directory). Credentials
come from the environment (REGISTRY_USERNAME + REGISTRY_PASSWORD or REGISTRY_TOKEN) or a
docker-style auth file (--auth-file, REGISTRY_AUTH_FILE, $DOCKER_CONFIG/config.json,
~/.docker/config.json), never from the command line. --insecure means plain http (a local
registry). --convert-only does steps 1-3 for every image without contacting a registry and
prints the computed digests (used to write the pins). Standard library only.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spinnaker_archive as sa  # noqa: E402


def layers(pin: sa.Pin, archive: sa.DockerArchive) -> list[tuple[str, int]]:
    """(digest, size) of each layer as pushed: the archive's own uncompressed tar. Each is
    hashed and must equal the diff_id in the config."""
    out = []
    for i, name in enumerate(archive.layer_names):
        t = time.time()
        with archive.layer(i) as src:
            digest, size = sa.hash_stream(src)
        if digest != archive.diff_ids[i]:
            raise sa.Error(f"{pin.service}: layer {i} ({name}) hashes to {digest}, "
                           f"the config says {archive.diff_ids[i]}")
        print(f"    layer {i + 1}/{len(archive.layer_names)} {digest[7:19]} {size:>11} bytes "
              f"{time.time() - t:5.1f}s", flush=True)
        out.append((digest, size))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--archive-dir", type=Path,
                   default=Path(os.environ["SPINNAKER_ARCHIVE_DIR"])
                   if os.environ.get("SPINNAKER_ARCHIVE_DIR") else None)
    p.add_argument("--namespace", help="registry namespace (default: registry.env)")
    p.add_argument("--only", action="append", help="push only this service (repeatable)")
    p.add_argument("--insecure", action="store_true", help="plain http (local registry)")
    p.add_argument("--auth-file")
    p.add_argument("--convert-only", action="store_true")
    p.add_argument("--result", type=Path, help="write the pushed digests as JSON")
    a = p.parse_args()
    if not a.archive_dir:
        p.error("--archive-dir (or SPINNAKER_ARCHIVE_DIR) is required")
    env, pins = sa.load_pins(a.only)
    ns = sa.namespace(a.namespace)
    host, _, base = ns.partition("/")
    reg = None if a.convert_only else sa.Registry(host, a.insecure, a.auth_file)
    print(f"==> {len(pins)} image(s), namespace {ns}", flush=True)
    results = []
    for pin in pins:
        t0 = time.time()
        print(f"==> {pin.service} {pin.version}", flush=True)
        archive = sa.check_archive(pin, a.archive_dir)
        print(f"    archive ok: sha256 {pin.archive_sha256[:12]}, config {pin.config_digest[7:19]}, "
              f"{pin.layers} layers", flush=True)
        blobs = layers(pin, archive)
        manifest = sa.build_manifest(pin, len(archive.config_bytes), blobs, env)
        digest = sa.digest_of(manifest)
        print(f"    manifest {digest} ({len(manifest)} bytes)", flush=True)
        if not a.convert_only and digest != pin.manifest_digest:
            raise sa.Error(f"{pin.service}: manifest digest {digest}, pinned {pin.manifest_digest}; "
                           "nothing was uploaded ")
        if a.convert_only:
            results.append({"service": pin.service, "manifest_digest": digest,
                            "matches_pin": digest == pin.manifest_digest})
        else:
            repo = f"{base}/{pin.repo_name}"
            for i, (d, size) in enumerate(blobs):
                t = time.time()
                state = reg.upload_blob(repo, d, size, lambda i=i: archive.layer(i))
                print(f"    blob {d[7:19]} {size:>11} bytes {state} {time.time() - t:5.1f}s",
                      flush=True)
            config = archive.config_bytes
            state = reg.upload_blob(repo, pin.config_digest, len(config),
                                    lambda: io.BytesIO(config))
            print(f"    config {pin.config_digest[7:19]} {state}", flush=True)
            got = reg.put_manifest(repo, pin.version, manifest, sa.MANIFEST_TYPE)
            if got != pin.manifest_digest:
                raise sa.Error(f"{pin.service}: registry reports manifest {got}, "
                               f"pinned {pin.manifest_digest}")
            print(f"    pushed {pin.reference(ns)}@{got}", flush=True)
            results.append({"service": pin.service, "version": pin.version,
                            "reference": pin.reference(ns), "digest": got,
                            "config_digest": pin.config_digest,
                            "archive_sha256": pin.archive_sha256, "origin": pin.origin,
                            "original_reference": pin.original,
                            "layers": [d for d, _ in blobs]})
        archive.close()
        print(f"    {time.time() - t0:.1f}s", flush=True)
    if a.result:
        a.result.write_text(json.dumps(results, indent=1) + "\n")
    print("==> done")


if __name__ == "__main__":
    try:
        main()
    except sa.Error as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
