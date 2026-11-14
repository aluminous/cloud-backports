#!/usr/bin/env python3
"""Inventory docker-archive tars of Spinnaker services, reading them in place.

    inventory-spinnaker.py ARCHIVE... [--json OUT.json]

For each archive: file sha256 and size, image config digest (the image ID), layer and diff_id
counts, os/architecture, labels, command, user, creation time, and what the layers contain:
/etc/os-release, the JVM `release` files, the dpkg package list and the packages whose
copyright file mentions the GPL. Used to write images/spinnaker/<release>/inputs.env and
NOTICE; run it again to check them. Standard library only. Does not modify the archives.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spinnaker_archive as sa  # noqa: E402

JVM_RELEASE = re.compile(r"^(?:\./)?(?:usr/lib/jvm|opt/java|usr/local/openjdk[^/]*|opt/openjdk[^/]*)/(?:[^/]+/)*release$")
COPYRIGHT = re.compile(r"^(?:\./)?usr/share/doc/([^/]+)/copyright$")
FILES = ("etc/os-release", "etc/alpine-release", "etc/debian_version", "var/lib/dpkg/status",
         "lib/apk/db/installed")


def norm(name: str) -> str:
    return name[2:] if name.startswith("./") else name


def scan(a: sa.DockerArchive) -> dict:
    files: dict[str, bytes] = {}
    jvm: dict[str, bytes] = {}
    copyright_gpl: dict[str, bool] = {}
    jvm_dirs: set[str] = set()
    for i in range(len(a.layer_names)):
        tf = a.layer_tar(i)
        for m in tf:
            n = norm(m.name)
            if n in FILES and m.isfile():
                files[n] = tf.extractfile(m).read()
            elif JVM_RELEASE.match(m.name) and m.isfile():
                jvm[n] = tf.extractfile(m).read()
            elif (c := COPYRIGHT.match(m.name)) and (m.isfile() or m.issym()):
                if m.isfile():
                    t = tf.extractfile(m).read().decode("utf-8", "replace")
                    copyright_gpl[c.group(1)] = bool(re.search(r"GPL|General Public", t))
            elif (j := re.match(r"^(usr/lib/jvm/[^/]+|opt/java/[^/]+|usr/local/openjdk[^/]*)$", n)):
                jvm_dirs.add(j.group(1))
    pkgs = []
    for block in files.get("var/lib/dpkg/status", b"").decode("utf-8", "replace").split("\n\n"):
        f = dict(re.findall(r"^(Package|Version|Architecture|Status): (.*)$", block, re.M))
        if f.get("Status", "").endswith("installed"):
            pkgs.append(f"{f['Package']}={f['Version']}")
    apk = []
    for block in files.get("lib/apk/db/installed", b"").decode("utf-8", "replace").split("\n\n"):
        f = {m.group(1): m.group(2) for m in re.finditer(r"^([A-Za-z]):(.*)$", block, re.M)}
        if "P" in f:
            apk.append({"name": f["P"], "version": f.get("V", ""), "origin": f.get("o", ""),
                        "license": f.get("L", ""), "url": f.get("U", ""),
                        "aports_commit": f.get("c", "")})
    return {
        "alpine_release": files.get("etc/alpine-release", b"").decode().strip(),
        "apk_packages": len(apk),
        "apk_list": apk,
        "os_release": files.get("etc/os-release", b"").decode(),
        "debian_version": files.get("etc/debian_version", b"").decode().strip(),
        "jvm_release_files": {k: v.decode() for k, v in jvm.items()},
        "jvm_dirs": sorted(jvm_dirs),
        "dpkg_packages": len(pkgs),
        "dpkg_list": pkgs,
        "copyright_files": len(copyright_gpl),
        "gpl_mentioning_packages": sorted(k for k, v in copyright_gpl.items() if v),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("archives", nargs="+", type=Path)
    p.add_argument("--json", type=Path)
    args = p.parse_args()
    out = []
    for path in args.archives:
        print(f"==> {path.name}", file=sys.stderr)
        a = sa.DockerArchive(path)
        c = a.config
        cc = c.get("config", {})
        info = {
            "archive": path.name,
            "archive_sha256": sa.sha256_file(path),
            "archive_bytes": path.stat().st_size,
            "format": "docker-archive (manifest.json, uncompressed layer tars)",
            "repo_tags": a.repo_tags,
            "config_digest": a.config_digest,
            "layers": len(a.layer_names),
            "diff_ids": len(a.diff_ids),
            "layer_names_equal_diff_ids": [n[:-4] for n in a.layer_names] == [d[7:] for d in a.diff_ids],
            "os": c["os"], "architecture": c["architecture"], "created": c.get("created"),
            "labels": cc.get("Labels"), "user": cc.get("User"), "cmd": cc.get("Cmd"),
            "entrypoint": cc.get("Entrypoint"), "env": cc.get("Env"),
            "exposed_ports": list((cc.get("ExposedPorts") or {}).keys()),
            "docker_version": c.get("docker_version"),
            **scan(a),
        }
        a.close()
        out.append(info)
        osr = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', info["os_release"], re.M))
        print(f"{info['archive_sha256']}  {info['archive_bytes']:>11}  {info['config_digest']}  "
              f"{info['layers']}/{info['diff_ids']} layers  {info['os']}/{info['architecture']}  "
              f"{osr.get('PRETTY_NAME', '?')} ({info['alpine_release'] or info['debian_version']})  "
              f"{info['apk_packages']} apk / {info['dpkg_packages']} dpkg packages")
    if args.json:
        args.json.write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
