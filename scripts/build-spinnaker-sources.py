#!/usr/bin/env python3
"""Build the source bundle for the copyleft packages in the Spinnaker archive images.

    build-spinnaker-sources.py [--list packages.tsv] [--extra sources-extra.tsv]
                               [--cache DIR] [--out FILE.tar] [--jobs N] [--seed-from OLD.tar]
                               [--list-only]

Input: images/spinnaker/1.25.4/packages.tsv (written by inventory-spinnaker.py: every apk and
dpkg package of the six images, with licence, class, aports commit, images) and
sources-extra.tsv (bundled components that are not distribution packages). For every source
package that has a binary package whose licence field names the GPL or LGPL (and, for Debian,
every source package with a binary package whose licence could not be classified):

  * Alpine (apk): every file of the package's aports directory at the recorded commit (the
    APKBUILD, patches, init scripts: all part of the corresponding source; each checked against
    its git blob id), and every remote source named in `source=`, from
    distfiles.alpinelinux.org/distfiles/<branch>/ or else the upstream URL, checked against the
    APKBUILD's sha512sums.
  * Debian (dpkg): the source package's files (.dsc, upstream tarball, debian tarball) from
    snapshot.debian.org, checked against the snapshot's sha1 and the .dsc's checksums.

The result is one uncompressed tar with sorted entries, mtime 0, owner root and mode 0644, whose
first entry is MANIFEST (package, version, licence, commit, images, every file with its sha512
and size, and anything that could not be fetched). Downloads are cached; the tar is rebuilt from
the cache. --seed-from takes packages that an earlier bundle already holds from that tar (every
file checked against its MANIFEST sha512) instead of downloading them. Exit status 1 if anything is missing (the tar is still written).
Standard library only.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import fnmatch
import hashlib
import io
import json
import re
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINDIR = ROOT / "images" / "spinnaker" / "1.25.4"
UA = {"User-Agent": "cloud-backports-spinnaker-sources/1"}
GITLAB = "https://gitlab.alpinelinux.org/api/v4/projects/alpine%2Faports/repository"
DISTFILES = "https://distfiles.alpinelinux.org/distfiles"
SNAPSHOT = "https://snapshot.debian.org"


class Missing(Exception):
    pass


# ---------------------------------------------------------------- HTTP with cache

class Fetcher:
    def __init__(self, cache: Path) -> None:
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)

    def get(self, url: str) -> Path:
        dest = self.cache / hashlib.sha256(url.encode()).hexdigest()
        if dest.is_file():
            return dest
        last = None
        for attempt in range(3):
            t0 = time.time()
            try:
                tmp = dest.with_suffix(".part")
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r, \
                        tmp.open("wb") as f:
                    while block := r.read(1 << 20):
                        f.write(block)
                tmp.rename(dest)
                return dest
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code in (403, 404, 410):
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = str(e)
            print(f"    retry {attempt + 1} after {time.time() - t0:.0f}s: {url} ({last})", flush=True)
            time.sleep(2 * (attempt + 1))
        raise Missing(f"{url}: {last}")

    def bytes(self, url: str) -> bytes:
        return self.get(url).read_bytes()


def digest_file(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        while block := f.read(1 << 20):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- APKBUILD evaluation

def expand(text: str, env: dict[str, str]) -> str:
    """Shell-style expansion of $var, ${var}, ${var%pat}, ${var#pat}, ${var/a/b}, ${var:-d}
    (what APKBUILD `source=` lines use). Anything else raises Missing."""
    def param(m: re.Match) -> str:
        body = m.group(1) or m.group(2)
        mm = re.fullmatch(r"(\w+)(.*)", body, re.S)
        name, op = mm.group(1), mm.group(2)
        v = env.get(name, "")
        if not op:
            return v
        if op.startswith(":-"):
            return v or expand(op[2:], env)
        kind = re.match(r"(%%|%|##|#|//|/)(.*)", op, re.S)
        if not kind:
            raise Missing(f"unsupported expansion ${{{body}}}")
        k, arg = kind.groups()
        if k in ("/", "//"):
            pat, _, rep = arg.partition("/")
            pat, rep = expand(pat, env), expand(rep, env)
            return re.sub(glob_re(pat), lambda _: rep, v, count=0 if k == "//" else 1)
        pat = glob_re(expand(arg, env))
        n = len(v)
        if k[0] == "#":  # remove a prefix: shortest (#) or longest (##)
            for i in (range(n, -1, -1) if k == "##" else range(0, n + 1)):
                if re.fullmatch(pat, v[:i], re.S):
                    return v[i:]
        else:  # remove a suffix: shortest (%) or longest (%%)
            for i in (range(0, n + 1) if k == "%%" else range(n, -1, -1)):
                if re.fullmatch(pat, v[i:], re.S):
                    return v[:i]
        return v

    out = re.sub(r"\$\{([^}]*)\}|\$(\w+)", param, text)
    if "$(" in out or "`" in out:
        raise Missing(f"command substitution in APKBUILD value: {text[:80]}")
    return out


def glob_re(pat: str) -> str:
    r = ""
    for c in pat:
        r += ".*" if c == "*" else "." if c == "?" else re.escape(c)
    return r


def parse_apkbuild(text: str) -> dict[str, str]:
    """Top-level variable assignments (not inside functions), in order, expanded."""
    env: dict[str, str] = {}
    lines = text.split("\n")
    i, in_func = 0, False
    while i < len(lines):
        line = lines[i]
        i += 1
        if in_func:
            in_func = not line.startswith("}")
            continue
        if re.match(r"^[\w-]+\(\)\s*\{?", line):
            in_func = not line.rstrip().endswith("}")
            continue
        m = re.match(r"^(\w+)=(.*)$", line)
        if not m:
            continue
        name, val = m.groups()
        if val and val[0] in "\"'":
            q = val[0]
            while val.count(q) < 2 and i < len(lines):
                val += "\n" + lines[i]
                i += 1
            val = val[1:val.rindex(q)]
        else:
            val = val.split(" #")[0].strip()
        try:
            env[name] = expand(val, env) if "$" in val else val
        except Missing:
            env[name] = "\0UNRESOLVED"
    return env


def apk_sources(env: dict[str, str]) -> list[tuple[str, str, str]]:
    """[(file name, url or "", sha512)] from source= and sha512sums=."""
    src = env.get("source", "")
    if "\0UNRESOLVED" in src:
        raise Missing("source= could not be expanded")
    sums = {}
    for m in re.finditer(r"^([0-9a-f]{128})\s+(\S+)", env.get("sha512sums", ""), re.M):
        sums[m.group(2)] = m.group(1)
    out = []
    for tok in src.split():
        if "::" in tok:
            name, url = tok.split("::", 1)
        elif "://" in tok:
            url, name = tok, tok.rsplit("/", 1)[-1]
        else:
            name, url = tok, ""
        if name not in sums:
            raise Missing(f"no sha512 for {name} in the APKBUILD")
        out.append((name, url, sums[name]))
    return out


# ---------------------------------------------------------------- collecting files

class Item:
    def __init__(self, kind: str, name: str, version: str, licence: str, ref: str,
                 images: str, classes: str) -> None:
        self.kind, self.name, self.version, self.licence = kind, name, version, licence
        self.ref, self.images, self.classes = ref, images, classes
        self.files: list[tuple[str, Path, str, int]] = []  # (path in tar, cache file, sha512, size)
        self.missing: list[str] = []
        self.notes: list[str] = []
        self.basis = ""

    @property
    def dirname(self) -> str:
        return f"{self.kind}/{self.name}-{self.version}".replace(":", "%3a")


def git_blob_id(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def collect_alpine(f: Fetcher, it: Item, branches: list[str]) -> None:
    commit = it.ref
    found = None
    for repo in ("main", "community", "testing"):
        url = f"{GITLAB}/tree?path={repo}/{it.name}&ref={commit}&per_page=100"
        try:
            tree = json.loads(f.bytes(url))
        except Missing:
            continue
        if any(e["name"] == "APKBUILD" for e in tree):
            found = (repo, tree)
            break
    if not found:
        it.missing.append(f"aports directory of {it.name} at {commit}")
        return
    repo, tree = found
    it.notes.append(f"aports {repo}/{it.name}@{commit}")
    env = {}
    for e in tree:
        if e["type"] != "blob":
            it.missing.append(f"{e['path']}: not a plain file")
            continue
        try:
            p = f.get(f"{GITLAB}/files/{urllib.parse.quote(e['path'], safe='')}/raw?ref={commit}")
        except Missing as ex:
            it.missing.append(str(ex))
            continue
        if git_blob_id(p) != e["id"]:
            it.missing.append(f"{e['path']}: git blob id mismatch")
            continue
        it.files.append((f"{it.dirname}/aports/{e['name']}", p, digest_file(p, "sha512"), p.stat().st_size))
        if e["name"] == "APKBUILD":
            env = parse_apkbuild(p.read_text())
    if not env:
        it.missing.append("APKBUILD missing or unreadable")
        return
    want = f"{env.get('pkgver')}-r{env.get('pkgrel')}"
    if want != it.version:
        it.notes.append(f"APKBUILD says {want}, the image has {it.version}")
    try:
        sources = apk_sources(env)
    except Missing as ex:
        it.missing.append(f"source= of the APKBUILD: {ex}")
        return
    have = {e["name"] for e in tree}
    for name, url, sha512 in sources:
        if not url:
            if name not in have:
                it.missing.append(f"{name}: named in source= but not in the aports directory")
            else:  # a local file: already fetched and git-verified; check the sha512 too
                got = next(x[2] for x in it.files if x[0].endswith("/aports/" + name))
                if got != sha512:
                    it.missing.append(f"{name}: sha512 differs from the APKBUILD")
            continue
        urls = [f"{DISTFILES}/{b}/{name}" for b in branches] + [url]
        err = []
        for u in urls:
            try:
                p = f.get(u)
            except Missing as ex:
                err.append(str(ex))
                continue
            if digest_file(p, "sha512") != sha512:
                err.append(f"{u}: sha512 mismatch")
                p.unlink()
                continue
            it.files.append((f"{it.dirname}/source/{name}", p, sha512, p.stat().st_size))
            break
        else:
            it.missing.append(f"{name}: " + "; ".join(err))


def collect_debian(f: Fetcher, it: Item) -> None:
    src, _, ver = it.ref.partition("=")
    data = None
    for v in dict.fromkeys([ver, ver.split(":", 1)[-1]]):
        try:
            data = json.loads(f.bytes(f"{SNAPSHOT}/mr/package/{urllib.parse.quote(src)}/"
                                      f"{urllib.parse.quote(v)}/srcfiles?fileinfo=1"))
            break
        except Missing:
            continue
    if not data or not data.get("result"):
        it.missing.append(f"snapshot.debian.org has no source files for {src} {ver}")
        return
    got: dict[str, Path] = {}
    for r in data["result"]:
        h = r["hash"]
        name = data["fileinfo"][h][0]["name"]
        try:
            p = f.get(f"{SNAPSHOT}/file/{h}")
        except Missing as ex:
            it.missing.append(f"{name}: {ex}")
            continue
        if digest_file(p, "sha1") != h:
            it.missing.append(f"{name}: sha1 differs from the snapshot's hash")
            p.unlink()
            continue
        got[name] = p
    dsc = next((p for n, p in got.items() if n.endswith(".dsc")), None)
    if dsc:  # every file the .dsc lists must be present with the listed sha256
        text = dsc.read_text(errors="replace")
        block = re.search(r"^Checksums-Sha256:\n((?: .*\n)+)", text, re.M)
        for line in (block.group(1).splitlines() if block else []):
            sha, size, name = line.split()
            if name not in got:
                same = [n for n, q in got.items() if digest_file(q, "sha256") == sha]
                if same:  # the snapshot knows the file under another name (first seen with an older version)
                    got[name] = got.pop(same[0])
                    it.notes.append(f"{name} is {same[0]} in the snapshot (same sha256 as the .dsc)")
                    continue
                p = find_in_other_versions(f, src, ver, name, sha)
                if p:
                    got[name] = p
                    it.notes.append(f"{name} taken from another version of {src} (same sha256 as the .dsc)")
                else:
                    it.missing.append(f"{name}: listed in the .dsc, not in the snapshot")
            elif digest_file(got[name], "sha256") != sha:
                it.missing.append(f"{name}: sha256 differs from the .dsc")
    else:
        it.missing.append(f"{src} {ver}: no .dsc")
    for name, p in sorted(got.items()):
        it.files.append((f"{it.dirname}/{name}", p, digest_file(p, "sha512"), p.stat().st_size))
    it.notes.append(f"snapshot.debian.org {src} {ver}")


def find_in_other_versions(f: Fetcher, src: str, ver: str, name: str, sha256: str) -> Path | None:
    """A file the .dsc lists but the snapshot omits for this version (a component tarball
    shared between package revisions): look through the other versions of the source package."""
    upstream = ver.rsplit("-", 1)[0]
    try:
        versions = [v["version"] for v in json.loads(f.bytes(
            f"{SNAPSHOT}/mr/package/{urllib.parse.quote(src)}/"))["result"]]
    except Missing:
        return None
    for v in sorted(versions, key=lambda v: (not v.startswith(upstream), v)):
        try:
            data = json.loads(f.bytes(f"{SNAPSHOT}/mr/package/{urllib.parse.quote(src)}/"
                                      f"{urllib.parse.quote(v)}/srcfiles?fileinfo=1"))
        except Missing:
            continue
        for r in data.get("result", []):
            if data["fileinfo"][r["hash"]][0]["name"] == name:
                try:
                    p = f.get(f"{SNAPSHOT}/file/{r['hash']}")
                except Missing:
                    continue
                if digest_file(p, "sha256") == sha256:
                    return p
    return None


def collect_extra(f: Fetcher, it: Item, url: str, sha256: str) -> None:
    try:
        p = f.get(url)
    except Missing as ex:
        it.missing.append(str(ex))
        return
    if digest_file(p, "sha256") != sha256:
        it.missing.append(f"{url}: sha256 {digest_file(p, 'sha256')}, pinned {sha256}")
        return
    it.files.append((f"{it.dirname}/{url.rsplit('/', 1)[-1]}", p, digest_file(p, "sha512"), p.stat().st_size))
    it.notes.append(url)


# ---------------------------------------------------------------- selection and output

def read_tsv(path: Path) -> list[list[str]]:
    return [l.rstrip("\n").split("\t") for l in path.read_text().splitlines()
            if l.strip() and not l.startswith("#")]


def select(rows: list[list[str]], only_copyleft_licences: bool = True) -> list[Item]:
    apk: dict[str, dict] = {}
    deb: dict[str, dict] = {}
    for kind, name, version, origin, lic, cls, commit, dist, images in rows:
        if cls != "gpl" and not (kind == "dpkg" and cls == "check"):
            continue  # Debian packages whose licence could not be classified are included too
        if kind == "apk":
            g = apk.setdefault(f"{origin}@{commit}", {"origin": origin, "commit": commit, "v": {},
                                                      "lic": set(), "images": set(), "dist": set(),
                                                      "bins": set()})
            g["v"][name] = version
            g["bins"].add(name)
        else:
            g = deb.setdefault(origin, {"v": {}, "lic": set(), "images": set(), "dist": set(), "bins": set()})
            g["bins"].add(name)
        g["lic"].add(lic)
        g.setdefault("cls", set()).add(cls)
        g["images"].update(images.split(","))
        g["dist"].update(dist.split(","))
    items: list[Item] = []
    for k, g in apk.items():
        version = g["v"].get(g["origin"]) or sorted(g["v"].values())[0]
        it = Item("alpine", g["origin"], version, "; ".join(sorted(g["lic"])), g["commit"],
                  ",".join(sorted(g["images"])), ",".join(sorted(g["bins"])))
        it.dist = sorted(g["dist"])
        it.basis = "gpl-lgpl"
        items.append(it)
    for k, g in deb.items():
        src, _, ver = k.partition("=")
        it = Item("debian", src, ver, "; ".join(sorted(g["lic"])), k, ",".join(sorted(g["images"])),
                  ",".join(sorted(g["bins"])))
        it.dist = sorted(g["dist"])
        it.basis = "gpl-lgpl" if "gpl" in g["cls"] else "unclassified"
        items.append(it)
    return sorted(items, key=lambda i: (i.kind, i.name, i.version))


def manifest_text(items: list[Item], extra: list[Item]) -> str:
    out = ["# Corresponding source of the GPL/LGPL-licensed packages in the Spinnaker 1.25.4 archive images,",
           "# and of the Debian packages of echo whose licence could not be classified (BASIS unclassified)",
           "# (built by scripts/build-spinnaker-sources.py from images/spinnaker/1.25.4/packages.tsv).",
           "# PACKAGE: kind name version; LICENCE, REFERENCE, BASIS (gpl-lgpl or unclassified), IMAGES, BINARY-PACKAGES",
           "# FILE: sha512 size path (relative to the top of this tar)",
           "# MISSING: something that could not be fetched or verified", ""]
    for it in items + extra:
        out.append(f"PACKAGE {it.kind} {it.name} {it.version}")
        out.append(f"  LICENCE {it.licence}")
        out.append(f"  REFERENCE {it.ref}")
        if it.basis:
            out.append(f"  BASIS {it.basis}")
        out.append(f"  IMAGES {it.images}")
        if it.classes:
            out.append(f"  BINARY-PACKAGES {it.classes}")
        for n in it.notes:
            out.append(f"  NOTE {n}")
        for path, _, sha, size in sorted(it.files):
            out.append(f"  FILE {sha} {size} {path}")
        for m in it.missing:
            out.append(f"  MISSING {m}")
        out.append("")
    return "\n".join(out)


def write_tar(dest: Path, items: list[Item], extra: list[Item], manifest: str) -> None:
    entries: dict[str, Path | bytes] = {"MANIFEST": manifest.encode()}
    for it in items + extra:
        for path, p, _, _ in it.files:
            entries[path] = p
    with dest.open("wb") as raw, tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tf:
        for name in ["MANIFEST"] + sorted(n for n in entries if n != "MANIFEST"):
            src = entries[name]
            ti = tarfile.TarInfo(name)
            ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname, ti.mode = 0, 0, 0, "", "", 0o644
            if isinstance(src, bytes):
                ti.size = len(src)
                tf.addfile(ti, io.BytesIO(src))
            else:
                ti.size = src.stat().st_size
                with src.open("rb") as fh:
                    tf.addfile(ti, fh)


def seed_items(seed: Path, cache: Path) -> dict[tuple[str, str, str], tuple[list, list[str]]]:
    """Read a bundle built earlier: for each package its files (extracted into the cache,
    each checked against the sha512 in the bundle's MANIFEST) and notes."""
    out: dict = {}
    d = cache / "seed"
    d.mkdir(parents=True, exist_ok=True)
    with tarfile.open(seed) as tf:
        manifest = tf.extractfile("MANIFEST").read().decode()
        cur = None
        for line in manifest.splitlines():
            if line.startswith("PACKAGE "):
                _, kind, name, version = line.split(" ", 3)
                cur = out[(kind, name, version)] = ([], [])
            elif cur is not None and line.startswith("  FILE "):
                _, sha, size, path = line.split(None, 3)
                dest = d / sha
                if not dest.is_file():
                    with tf.extractfile(path) as src, dest.open("wb") as dst:
                        while block := src.read(1 << 20):
                            dst.write(block)
                if digest_file(dest, "sha512") != sha:
                    raise SystemExit(f"seed {seed}: {path} does not match its sha512 in MANIFEST")
                cur[0].append((path, dest, sha, int(size)))
            elif cur is not None and line.startswith("  NOTE "):
                cur[1].append(line[7:])
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--list", type=Path, default=PINDIR / "packages.tsv")
    p.add_argument("--extra", type=Path, default=PINDIR / "sources-extra.tsv")
    p.add_argument("--cache", type=Path, default=ROOT / "out" / "sources-cache")
    p.add_argument("--out", type=Path, default=ROOT / "out" / "spinnaker-1.25.4-sources.tar")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--seed-from", type=Path, help="an earlier bundle: packages in it are taken "
                   "from it (files verified against its MANIFEST) instead of downloaded")
    p.add_argument("--list-only", action="store_true", help="print the selected packages and stop")
    a = p.parse_args()
    items = select(read_tsv(a.list))
    extra: list[Item] = []
    extra_args: list[tuple[Item, str, str]] = []
    if a.extra.is_file():
        for name, version, lic, url, sha256, images, *_ in read_tsv(a.extra):
            it = Item("extra", name, version, lic, url, images, "")
            extra.append(it)
            extra_args.append((it, url, sha256))
    print(f"{len(items)} source packages (GPL/LGPL, or unclassified Debian) "
          f"({sum(i.kind == 'alpine' for i in items)} alpine, {sum(i.kind == 'debian' for i in items)} debian), "
          f"{len(extra)} extra", flush=True)
    if a.list_only:
        for i in items:
            print(i.kind, i.name, i.version, i.licence, i.images)
        return
    f = Fetcher(a.cache)
    todo = items
    if a.seed_from:
        seeded = seed_items(a.seed_from, a.cache)
        todo = []
        for it in items:
            got = seeded.get((it.kind, it.name, it.version))
            if got:
                it.files, it.notes = list(got[0]), list(got[1])
            else:
                todo.append(it)
        print(f"{len(items) - len(todo)} packages taken from {a.seed_from.name}, {len(todo)} to fetch", flush=True)

    def work(it: Item) -> Item:
        try:
            if it.kind == "alpine":
                collect_alpine(f, it, [d.split("-")[0] for d in it.dist if d.startswith("v")] + ["edge"])
            else:
                collect_debian(f, it)
        except Missing as ex:
            it.missing.append(str(ex))
        except Exception as ex:  # keep going; the failure is reported as missing
            import traceback
            traceback.print_exc()
            it.missing.append(f"internal error: {type(ex).__name__}: {ex}")
        print(f"  {it.kind:7} {it.name}-{it.version}: {len(it.files)} files"
              + (f", {len(it.missing)} MISSING" if it.missing else ""), flush=True)
        return it

    with cf.ThreadPoolExecutor(a.jobs) as ex:
        list(ex.map(work, todo))
    for it, url, sha in extra_args:
        collect_extra(f, it, url, sha)
        print(f"  extra   {it.name}-{it.version}: {len(it.files)} files"
              + (f", {len(it.missing)} MISSING" if it.missing else ""), flush=True)
    manifest = manifest_text(items, extra)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    write_tar(a.out, items, extra, manifest)
    h = digest_file(a.out, "sha256")
    files = sum(len(i.files) for i in items + extra)
    missing = [(i, m) for i in items + extra for m in i.missing]
    print(f"{a.out}: {a.out.stat().st_size} bytes, sha256 {h}, {files} files, {len(missing)} missing")
    by_kind: dict[str, int] = {}
    for i in items + extra:
        by_kind[i.kind] = by_kind.get(i.kind, 0) + sum(x[3] for x in i.files)
    print("bytes by kind:", by_kind)
    for i, m in missing:
        print(f"MISSING {i.kind} {i.name}-{i.version}: {m}")
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
