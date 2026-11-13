#!/usr/bin/env python3
"""Write Go's module download cache as a deterministic tar (or check one).

    module_tar.py write <GOMODCACHE>/cache/download <out.tar>
    module_tar.py sha256 <file>

Only the files a build reads are kept (`.mod`, `.zip`, `.ziphash`, `.info`; not the `.lock`
and `list` files), sorted, as `cache/download/<path>` with mtime 0, owner 0:0, mode 0644 and
no user or group names, PAX format. The same module set gives the same bytes, so its
sha256 can be pinned (inputs.env: MODULES_SHA256). Extract it into an empty GOMODCACHE and
build with GOPROXY=off and no network (BUILDING.md, "Fully offline").

Standard library only. The layout is byte-identical to Mockyard's capture
(mockyard.fetch.pilot.write_module_tar) with the same Python version (checked with 3.13).
"""

from __future__ import annotations

import hashlib
import sys
import tarfile
from pathlib import Path

SUFFIXES = (".mod", ".zip", ".ziphash", ".info")


def write(download_dir: Path, out: Path) -> int:
    files = sorted(p for p in download_dir.rglob("*")
                   if p.is_file() and p.name.endswith(SUFFIXES))
    with tarfile.open(out, "w", format=tarfile.PAX_FORMAT) as tf:
        for p in files:
            ti = tarfile.TarInfo("cache/download/" + p.relative_to(download_dir).as_posix())
            ti.size, ti.mtime, ti.mode, ti.uid, ti.gid = p.stat().st_size, 0, 0o644, 0, 0
            ti.uname = ti.gname = ""
            with p.open("rb") as f:
                tf.addfile(ti, f)
    return len(files)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "write":
        n = write(Path(argv[1]), Path(argv[2]))
        print(f"{n} files -> {argv[2]} sha256 {sha256(Path(argv[2]))}")
        return 0
    if len(argv) == 2 and argv[0] == "sha256":
        print(sha256(Path(argv[1])))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
