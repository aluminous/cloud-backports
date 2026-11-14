"""Shared code of the Spinnaker archive scripts (standard library only).

* the pins file (images/spinnaker/<release>/inputs.env)
* reading a docker-archive tar (manifest.json, config, layer tars)
* the OCI manifest built from an archive's own bytes (uncompressed layers, so the registry
  blobs are the archive's layer tars and nothing depends on a compressor)
* a small registry client (Distribution API v2: bearer or basic auth, chunked blob upload,
  manifest put/get)

Used by push-spinnaker.py, verify-spinnaker.py and inventory-spinnaker.py.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import re
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "1.25.4"
PINS_FILE = ROOT / "images" / "spinnaker" / RELEASE / "inputs.env"

# Layers are pushed exactly as they are in the archive: uncompressed tars (OCI media type
# layer.v1.tar), so a layer's blob digest is its diff_id and the manifest depends on nothing
# but the archive. (Compressing them would make the digests depend on the deflate
# implementation: classic zlib and zlib-ng give different bytes for the same level.)
LAYER_TYPE = "application/vnd.oci.image.layer.v1.tar"
CONFIG_TYPE = "application/vnd.oci.image.config.v1+json"
MANIFEST_TYPE = "application/vnd.oci.image.manifest.v1+json"
INDEX_TYPE = "application/vnd.oci.image.index.v1+json"
DOCKER_MANIFEST_TYPE = "application/vnd.docker.distribution.manifest.v2+json"
CHUNK = 32 * 1024 * 1024
BLOCK = 1024 * 1024


class Error(Exception):
    """A mismatch or failure that must stop the run with a non-zero exit status."""


# ---------------------------------------------------------------- pins

def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v.strip().strip('"')
    return out


class Pin:
    """The pinned facts of one image."""

    def __init__(self, env: dict[str, str], service: str) -> None:
        p = service.upper().replace("-", "_") + "_"
        self.service = service
        self.version = env[p + "VERSION"]
        self.original = env[p + "ORIGINAL_REFERENCE"]
        self.archive = env[p + "ARCHIVE"]
        self.archive_sha256 = env[p + "ARCHIVE_SHA256"]
        self.config_digest = env[p + "CONFIG_DIGEST"]
        self.layers = int(env[p + "LAYERS"])
        self.manifest_digest = env[p + "MANIFEST_DIGEST"]
        self.origin = env[p + "ORIGIN"]
        self.repo_name = "spinnaker-" + service  # <namespace>/<repo_name>:<version>

    def reference(self, namespace: str) -> str:
        return f"{namespace}/{self.repo_name}:{self.version}"


def load_pins(only: list[str] | None = None) -> tuple[dict[str, str], list[Pin]]:
    env = read_env(PINS_FILE)
    services = env["SERVICES"].split()
    for s in only or []:
        if s not in services:
            raise Error(f"unknown service {s!r}; pinned: {' '.join(services)}")
    return env, [Pin(env, s) for s in services if not only or s in only]


def namespace(override: str | None) -> str:
    if override:
        return override.rstrip("/")
    return read_env(ROOT / "registry.env")["IMAGE_NAMESPACE"].rstrip("/")


# ---------------------------------------------------------------- hashing

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(BLOCK):
            h.update(block)
    return h.hexdigest()


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- docker-archive

class DockerArchive:
    """A `docker save` / `podman save` tar (docker-archive format) with exactly one image."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.tar = tarfile.open(path, "r:")
        try:
            entries = json.load(self._file("manifest.json"))
        except KeyError:
            raise Error(f"{path.name}: no manifest.json (not a docker-archive)") from None
        if len(entries) != 1:
            raise Error(f"{path.name}: {len(entries)} images in the archive, expected 1")
        self.entry = entries[0]
        self.repo_tags: list[str] = self.entry.get("RepoTags") or []
        self.layer_names: list[str] = self.entry["Layers"]
        self.config_name: str = self.entry["Config"]
        self.config_bytes = self._file(self.config_name).read()
        self.config = json.loads(self.config_bytes)
        self.config_digest = digest_of(self.config_bytes)
        self.diff_ids: list[str] = self.config["rootfs"]["diff_ids"]

    def _file(self, name: str):
        f = self.tar.extractfile(name)
        if f is None:
            raise KeyError(name)
        return f

    def layer(self, index: int):
        return self._file(self.layer_names[index])

    def layer_size(self, index: int) -> int:
        return self.tar.getmember(self.layer_names[index]).size

    def layer_tar(self, index: int) -> tarfile.TarFile:
        return tarfile.open(fileobj=self.layer(index), mode="r:")

    def close(self) -> None:
        self.tar.close()


def check_archive(pin: Pin, directory: Path) -> DockerArchive:
    """Verify the archive file against the pins (file sha256, config digest, layer count)."""
    path = directory / pin.archive
    if not path.is_file():
        raise Error(f"{pin.service}: archive not found: {path}")
    got = sha256_file(path)
    if got != pin.archive_sha256:
        raise Error(f"{pin.service}: archive sha256 {got}, pinned {pin.archive_sha256}")
    a = DockerArchive(path)
    if a.config_digest != pin.config_digest:
        raise Error(f"{pin.service}: config digest {a.config_digest}, pinned {pin.config_digest}")
    if not (len(a.diff_ids) == len(a.layer_names) == pin.layers):
        raise Error(f"{pin.service}: {len(a.layer_names)} layers / {len(a.diff_ids)} diff_ids, "
                    f"pinned {pin.layers}")
    return a


# ---------------------------------------------------------------- manifest

def hash_stream(src) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    while block := src.read(BLOCK):
        h.update(block)
        n += len(block)
    return "sha256:" + h.hexdigest(), n


def build_manifest(pin: Pin, config_size: int, layers: list[tuple[str, int]],
                   env: dict[str, str]) -> bytes:
    """The OCI image manifest as bytes: fixed key order, no timestamps, nothing machine-specific."""
    ann = {
        "org.opencontainers.image.title": f"spinnaker-{pin.service}",
        "org.opencontainers.image.version": pin.version,
        "org.opencontainers.image.description":
            f"Spinnaker {env['SPINNAKER_RELEASE']} {pin.service}, archived unmodified from "
            f"{pin.original}",
        "org.opencontainers.image.licenses": "Apache-2.0",
        "org.opencontainers.image.source": env["SOURCE_REPOSITORY"],
        "dev.cloud-backports.original-reference": pin.original,
        "dev.cloud-backports.image-id": pin.config_digest,
    }
    doc = {
        "schemaVersion": 2,
        "mediaType": MANIFEST_TYPE,
        "config": {"mediaType": CONFIG_TYPE, "digest": pin.config_digest, "size": config_size},
        "layers": [{"mediaType": LAYER_TYPE, "digest": d, "size": s} for d, s in layers],
        "annotations": ann,
    }
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()


# ---------------------------------------------------------------- registry client

def split_reference(ref: str) -> tuple[str, str, str]:
    """`host[:port]/path/name:tag` -> (host, repository path, tag-or-digest)."""
    ref = ref.split("://", 1)[-1]
    host, _, rest = ref.partition("/")
    if "@" in rest:
        repo, _, tag = rest.partition("@")
    elif ":" in rest.rsplit("/", 1)[-1]:
        repo, _, tag = rest.rpartition(":")
    else:
        repo, tag = rest, "latest"
    return host, repo, tag


def load_credentials(host: str, auth_file: str | None) -> tuple[str, str] | None:
    """Credentials for `host`: REGISTRY_USERNAME + REGISTRY_PASSWORD (or REGISTRY_TOKEN), else a
    docker-style auth file (--auth-file, REGISTRY_AUTH_FILE, $DOCKER_CONFIG/config.json,
    ~/.docker/config.json, $XDG_RUNTIME_DIR/containers/auth.json). Never from the command line."""
    user = os.environ.get("REGISTRY_USERNAME")
    pw = os.environ.get("REGISTRY_PASSWORD") or os.environ.get("REGISTRY_TOKEN")
    if pw:
        return (user or "token", pw)
    candidates = [auth_file, os.environ.get("REGISTRY_AUTH_FILE")]
    if os.environ.get("DOCKER_CONFIG"):
        candidates.append(os.path.join(os.environ["DOCKER_CONFIG"], "config.json"))
    candidates.append(os.path.expanduser("~/.docker/config.json"))
    if os.environ.get("XDG_RUNTIME_DIR"):
        candidates.append(os.path.join(os.environ["XDG_RUNTIME_DIR"], "containers", "auth.json"))
    for c in candidates:
        if not c or not os.path.isfile(c):
            continue
        auths = json.loads(Path(c).read_text()).get("auths", {})
        for key in (host, f"https://{host}", f"http://{host}"):
            e = auths.get(key)
            if e and e.get("auth"):
                u, _, p = base64.b64decode(e["auth"]).decode().partition(":")
                return u, p
            if e and e.get("username") and e.get("password"):
                return e["username"], e["password"]
    return None


class Registry:
    """One registry host. `insecure` means plain http (a local throwaway registry)."""

    def __init__(self, host: str, insecure: bool = False, auth_file: str | None = None) -> None:
        self.host = host
        self.insecure = insecure
        self.creds = load_credentials(host, auth_file)
        self.tokens: dict[str, str] = {}  # scope -> bearer token
        self.basic = False

    # -- transport
    def _conn(self, host: str | None = None, https: bool | None = None):
        host = host or self.host
        https = (not self.insecure) if https is None else https
        cls = http.client.HTTPSConnection if https else http.client.HTTPConnection
        return cls(host, timeout=600)

    def _auth_header(self, scope: str) -> dict[str, str]:
        if scope in self.tokens:
            return {"Authorization": "Bearer " + self.tokens[scope]}
        if self.basic and self.creds:
            return {"Authorization": "Basic " + base64.b64encode(
                f"{self.creds[0]}:{self.creds[1]}".encode()).decode()}
        return {}

    def _challenge(self, www: str, scope: str) -> None:
        kind, _, params = www.partition(" ")
        if kind.lower() == "basic":
            if not self.creds:
                raise Error(f"{self.host} wants credentials; none found (see BUILDING.md)")
            self.basic = True
            return
        p = dict(re.findall(r'(\w+)="([^"]*)"', params))
        q = {"service": p.get("service", ""), "scope": p.get("scope") or scope}
        url = p["realm"] + "?" + urllib.parse.urlencode({k: v for k, v in q.items() if v})
        headers = {"User-Agent": "cloud-backports-spinnaker/1"}
        if self.creds:
            headers["Authorization"] = "Basic " + base64.b64encode(
                f"{self.creds[0]}:{self.creds[1]}".encode()).decode()
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
            doc = json.load(r)
        self.tokens[scope] = doc.get("token") or doc.get("access_token")

    def request(self, method: str, path: str, repo: str, actions: str, body=None,
                headers: dict[str, str] | None = None, length: int | None = None):
        """One request with auth retry. `path` is absolute (/v2/...) or a full URL.
        Returns (status, response headers, body bytes)."""
        scope = f"repository:{repo}:{actions}"
        for attempt in range(3):
            h = {"User-Agent": "cloud-backports-spinnaker/1", **self._auth_header(scope),
                 **(headers or {})}
            if length is not None:
                h["Content-Length"] = str(length)
            url = urllib.parse.urlsplit(path)
            conn = self._conn(url.netloc or None, (url.scheme == "https") if url.scheme else None)
            try:
                target = url.path + (("?" + url.query) if url.query else "")
                if hasattr(body, "read") and length is not None:
                    conn.putrequest(method, target)
                    for k, v in h.items():
                        conn.putheader(k, v)
                    conn.endheaders()
                    while block := body.read(BLOCK):
                        conn.send(block)
                else:
                    conn.request(method, target, body=body, headers=h)
                resp = conn.getresponse()
                data = resp.read()
                hdrs = {k.lower(): v for k, v in resp.getheaders()}
            finally:
                conn.close()
            if resp.status == 401 and attempt < 2:
                if hasattr(body, "seek"):
                    body.seek(0)
                self._challenge(hdrs.get("www-authenticate", ""), scope)
                continue
            if resp.status in (301, 302, 307, 308) and "location" in hdrs:
                path = urllib.parse.urljoin(f"https://{self.host}{path}", hdrs["location"]) \
                    if not path.startswith("http") else urllib.parse.urljoin(path, hdrs["location"])
                continue
            return resp.status, hdrs, data
        raise Error(f"{self.host}: authentication failed for {method} {path}")

    # -- blobs
    def blob_exists(self, repo: str, digest: str) -> bool:
        s, _, _ = self.request("HEAD", f"/v2/{repo}/blobs/{digest}", repo, "pull")
        return s == 200

    def get_blob(self, repo: str, digest: str) -> bytes:
        s, _, data = self.request("GET", f"/v2/{repo}/blobs/{digest}", repo, "pull")
        if s != 200:
            raise Error(f"GET blob {digest} from {repo}: HTTP {s}")
        return data

    def upload_blob(self, repo: str, digest: str, size: int, source) -> str:
        """Upload one blob (chunked) unless the repository already has it.
        Returns 'exists' or 'uploaded'."""
        if self.blob_exists(repo, digest):
            return "exists"
        s, h, _ = self.request("POST", f"/v2/{repo}/blobs/uploads/", repo, "pull,push",
                               headers={"Content-Length": "0"})
        if s != 202:
            raise Error(f"start upload to {repo}: HTTP {s}")
        loc = h["location"]
        if loc.startswith("/"):
            loc = ("http://" if self.insecure else "https://") + self.host + loc
        with source() as f:
            offset = 0
            while offset < size:
                n = min(CHUNK, size - offset)
                chunk = f.read(n)
                s, h, body = self.request(
                    "PATCH", loc, repo, "pull,push", body=chunk,
                    headers={"Content-Type": "application/octet-stream",
                             "Content-Range": f"{offset}-{offset + n - 1}"})
                if s != 202:
                    raise Error(f"upload chunk to {repo}: HTTP {s} {body[:200]!r}")
                loc = h.get("location", loc)
                if loc.startswith("/"):
                    loc = ("http://" if self.insecure else "https://") + self.host + loc
                offset += n
        sep = "&" if "?" in loc else "?"
        s, h, body = self.request("PUT", f"{loc}{sep}digest={digest}", repo, "pull,push",
                                  headers={"Content-Length": "0"})
        if s != 201:
            raise Error(f"finish upload of {digest} to {repo}: HTTP {s} {body[:200]!r}")
        if h.get("docker-content-digest", digest) != digest:
            raise Error(f"registry reports digest {h['docker-content-digest']} for {digest}")
        return "uploaded"

    # -- manifests
    def put_manifest(self, repo: str, ref: str, manifest: bytes, media_type: str) -> str:
        s, h, body = self.request("PUT", f"/v2/{repo}/manifests/{ref}", repo, "pull,push",
                                  body=manifest, headers={"Content-Type": media_type})
        if s not in (200, 201):
            raise Error(f"put manifest {repo}:{ref}: HTTP {s} {body[:300]!r}")
        return h.get("docker-content-digest", digest_of(manifest))

    def get_manifest(self, repo: str, ref: str) -> tuple[bytes, str]:
        accept = ", ".join([MANIFEST_TYPE, DOCKER_MANIFEST_TYPE, INDEX_TYPE])
        s, h, data = self.request("GET", f"/v2/{repo}/manifests/{ref}", repo, "pull",
                                  headers={"Accept": accept})
        if s != 200:
            raise Error(f"GET manifest {repo}:{ref}: HTTP {s}")
        return data, h.get("content-type", "")

