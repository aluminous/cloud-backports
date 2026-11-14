#!/usr/bin/env python3
"""Measure what compressing the layers of the Spinnaker archives would save.

    measure-spinnaker-compression.py --archive-dir DIR [--json OUT.json]

For each pinned archive, the total bytes of its layer tars as they are, and compressed with
gzip level 6 and 9 (zlib) and zstd level 3 and 19 (Python 3.14+ `compression.zstd`, 4 worker
threads). Nothing is written except the optional JSON; the pushed images stay uncompressed.
"""

from __future__ import annotations

import argparse
import json
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spinnaker_archive as sa  # noqa: E402


def sizes(a: sa.DockerArchive, zstd) -> dict[str, int]:
    out = {"raw": 0, "gzip6": 0, "gzip9": 0, "zstd3": 0, "zstd19": 0}
    for i in range(len(a.layer_names)):
        z6, z9 = zlib.compressobj(6, zlib.DEFLATED, 31), zlib.compressobj(9, zlib.DEFLATED, 31)
        s3 = zstd.ZstdCompressor(options={zstd.CompressionParameter.compression_level: 3, zstd.CompressionParameter.nb_workers: 4})
        s19 = zstd.ZstdCompressor(options={zstd.CompressionParameter.compression_level: 19, zstd.CompressionParameter.nb_workers: 4})
        with a.layer(i) as f:
            while block := f.read(sa.BLOCK):
                out["raw"] += len(block)
                out["gzip6"] += len(z6.compress(block))
                out["gzip9"] += len(z9.compress(block))
                out["zstd3"] += len(s3.compress(block))
                out["zstd19"] += len(s19.compress(block))
        out["gzip6"] += len(z6.flush())
        out["gzip9"] += len(z9.flush())
        out["zstd3"] += len(s3.flush())
        out["zstd19"] += len(s19.flush())
    return out


def main() -> None:
    from compression import zstd
    p = argparse.ArgumentParser()
    p.add_argument("--archive-dir", type=Path, required=True)
    p.add_argument("--json", type=Path)
    a = p.parse_args()
    _, pins = sa.load_pins()
    result, total = {}, {}
    for pin in pins:
        if pin.mode != "archive":
            continue
        ar = sa.DockerArchive(a.archive_dir / pin.archive)
        r = sizes(ar, zstd)
        ar.close()
        result[pin.service] = r
        for k, v in r.items():
            total[k] = total.get(k, 0) + v
        print(pin.service, r, flush=True)
    result["total"] = total
    print("total", total)
    if a.json:
        a.json.write_text(json.dumps(result, indent=1) + "\n")


if __name__ == "__main__":
    main()
