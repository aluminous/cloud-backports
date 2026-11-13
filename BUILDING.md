# Building from source

Everything an image is built from is pinned in `images/<image>/<version>/inputs.env`. A
build that does not reproduce the pinned binary sha256 fails; please report it.

## istio-pilot 1.10.6 (linux/arm64)

Requirements: an arm64 machine (macOS on Apple Silicon with Podman or Docker Desktop, or
arm64 Linux), `bash`, `curl`, `python3` (3.11+, standard library only), `git`, Docker or
Podman, about 2 GB free disk and 4 GB of memory for the container engine. On macOS the
checkout must be inside a folder the Podman/Docker VM shares (by default your home folder).

```bash
scripts/build-istio-pilot.sh                  # compile + verify; --engine podman to choose
scripts/image-build.sh                        # package: $IMAGE_NAMESPACE/istio-pilot:1.10.6-arm64
scripts/verify-image.sh ghcr.io/aluminous/cloud-backports/istio-pilot:1.10.6-arm64
```

What `build-istio-pilot.sh` does:

1. Downloads `https://github.com/istio/istio/archive/refs/tags/1.10.6.tar.gz` into `.cache/`
   and checks its sha256 (`c737648a…aae4`).
2. Runs the pinned Go toolchain image (`golang:1.16.9` by index digest) as a container:
   `go build -trimpath` of `./pilot/cmd/pilot-discovery` with `CGO_ENABLED=0`,
   `GOFLAGS=-mod=readonly`, `GOSUMDB=off` (every module is checked against the release's own
   `go.sum` instead) and upstream's release ldflags (`common/scripts/gobuild.sh` and
   `report_build_info.sh`: `-extldflags -static`, version `1.10.6`, revision
   `fd053c61…`, status `Clean`, tag `1.10.6`, hub `docker.io/istio`). The binary is not
   stripped, like upstream's.
3. Checks the result: an AArch64 ELF, sha256 equal to `BINARY_SHA256_ARM64`, and
   `pilot-discovery version -o json` (run with no network) reporting `1.10.6`,
   `fd053c6165d21105d66dac6e3d0649db2dde5b86`, `Clean`, `go1.16.9`.
4. Stages `out/istio-pilot-1.10.6/context/`: the binary, Istio's `LICENSE`, the `licenses/`
   folder of the source (the licences of the Go modules linked into the binary), `NOTICE`
   and `BUILD-METADATA.json`.

`image-build.sh` then runs an ordinary `docker|podman build` of
`images/istio-pilot/1.10.6/Containerfile` on the pinned distroless base. The image digest
depends on the build tool (layer compression, timestamps); the **binary** is what is pinned
and checked, so compare binaries (`verify-image.sh`), not image digests.

### Expected output

| Output | sha256 |
|---|---|
| Source tarball | `c737648a6dc6b4bb3a5ac1dfc202469ced73e54c83cc591db917120c5590aae4` |
| Go module set (`--save-modules`, 1892 files, 110 MB) | `cc8af5e960238679557d57af2e2bf0b652d62fee6603ad8247a265a90389ffff` |
| `pilot-discovery` linux/arm64 (111,774,968 bytes) | `b851b0b5af62ea9b57f2ef51b5c7ee31e624d6e4c1f06a3892c5acb778973c44` |

The same binary came out of four independent builds before this repository existed (in
Mockyard's recipe, on an Apple Silicon Mac with Podman: twice with modules downloaded from
proxy.golang.org, twice offline from the saved module set). A build in a `linux/amd64`
toolchain container cross-compiling to arm64 (`--platform linux/amd64`) is expected to give
the same bytes (Go builds are reproducible across hosts with `-trimpath`), but that has not
been checked.

Measured with this repository's scripts (Apple Silicon, Podman 5, 2026-11-13): an online
build and an offline build from the saved module tar both gave the binary
`b851b0b5…3c44` and `version` 1.10.6 / `fd053c61…` / Clean / go1.16.9; `--save-modules`
wrote the module tar `cc8af5e9…ffff` (with Python 3.15: the tar layout does not depend on the
Python version there); `verify-image.sh` passed on the image `image-build.sh` produced, and
that image ran as istiod in a Kubernetes 1.21 Kind cluster (Mockyard's legacy lane).

### How long

On an Apple Silicon Mac (Podman machine, 5 CPUs), with these scripts: 61 s for an online
build (module download and compile), 56 s for an offline build from the saved module set,
8 s for the image. (Mockyard's recipe, which also captures the module set, took 110-130 s.) Pulling the Go builder image the first time adds its
305 MB download.

### Network access the first build needs

| Host | For |
|---|---|
| `github.com`, `codeload.github.com` | the source tarball |
| `registry-1.docker.io`, `auth.docker.io`, `production.cloudflare.docker.com` | the Go builder image |
| `gcr.io` (and its storage hosts) | the distroless base |
| `proxy.golang.org` | the Go modules, **from inside the toolchain container** (about 113 MB); set `GOPROXY_OVERRIDE=https://goproxy.corp.example` to use a mirror |

The module download happens inside the container, so a TLS-intercepting proxy must be
trusted there too (mount its CA and set `SSL_CERT_FILE` by editing the `run` line, or use an
internal GOPROXY, or build offline as below). `sum.golang.org` is not contacted
(`GOSUMDB=off`; `go.sum` from the pinned source is the check).

### Fully offline

On a machine with network access:

```bash
scripts/build-istio-pilot.sh --save-modules istio-go-modules-1.10.6.tar   # checks MODULES_SHA256
docker save -o golang-1.16.9.tar "$(. images/istio-pilot/1.10.6/inputs.env; echo "$GO_BUILDER")"
docker save -o distroless.tar   "$(. images/istio-pilot/1.10.6/inputs.env; echo "$BASE_IMAGE")"
cp .cache/istio-1.10.6.tar.gz .
```

(each CI run also uploads the module set as the artifact `istio-go-modules-1.10.6`). Carry the
four files across, `docker load` the two images, put the source tarball into `.cache/`, then:

```bash
scripts/build-istio-pilot.sh --modules-tar istio-go-modules-1.10.6.tar
scripts/image-build.sh
```

The compile container then runs with `--network none` and `GOPROXY=off`; the module tar is
checked against `MODULES_SHA256` before it is used. `module_tar.py` writes the same bytes as
Mockyard's own capture (same file selection, order and tar metadata) with the same Python
version; checked with Python 3.13 (Mockyard) and 3.15 (this script) giving the same sha.

### Podman notes

`--engine podman` works rootful or rootless. On macOS the bind mounts (`-v`) need the
checkout under a path the Podman machine shares (`/Users` by default).
