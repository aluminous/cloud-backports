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

## Spinnaker 1.25.4 archive (publishing)

This is not a build: the images are upstream's, saved earlier, and are pushed as they are.
Five of them (clouddriver, front50, gate, orca, rosco) exist only as the archive files named in
[`images/spinnaker/1.25.4/inputs.env`](images/spinnaker/1.25.4/inputs.env) (the old test
harness's bundle cache, `.tools/bundle-cache/<id>/images/`; read in place, never modified).
The sixth, echo 2.15.0-20201009170017, is copied from `gcr.io/spinnaker-marketplace/echo` by
digest. Alongside the images a **source bundle** with the corresponding source of the
GPL/LGPL-licensed packages is released.

### Checklist: how the archive was published, and how to publish a new archive release

This is the route used for `spinnaker-1.25.4`; for a new release, change the pins and the tag
name. It needs no personal access token: the archives and the source bundle are uploaded once
as assets of a GitHub release, and a workflow downloads them and pushes with the job's own
`GITHUB_TOKEN` (`packages: write`).

1. Merge the branch to the default branch. The draft release is created without a target, so
   publishing it (step 5) creates the tag at the head of the default branch, and the workflow
   file is read from that tagged commit; a manual run (`workflow_dispatch`) also needs the
   workflow file on the default branch.
2. On the machine that holds the archives, build the source bundle (needs the network; about
   an hour or more, mostly waiting for the mirrors; downloads are cached and resumable; the result is pinned):
   `scripts/build-spinnaker-sources.py --out out/spinnaker-1.25.4-sources.tar` and check that it
   prints no `MISSING` line and the sha256 in `inputs.env` (`SOURCES_BUNDLE_SHA256`). If you
   already hold an earlier copy of the bundle, `--seed-from OLD.tar` reuses its files (checked
   against its MANIFEST) and downloads only what is new.
3. Check everything against the pins, without touching GitHub (`ARCHIVES` is the directory with
   the five archive files, as in the manual route below):
   `scripts/create-spinnaker-release.sh --archive-dir "$ARCHIVES" --sources-tar out/spinnaker-1.25.4-sources.tar`
   (prints what it would upload).
4. Create the draft release and upload the files (the five archives and the source bundle,
   about 3.8 GB; each is under the 2 GiB asset limit, clouddriver is 1.6 GB): the same command
   with `--run`, with `gh` logged in as a user who may create releases (`gh auth login`).
5. In the GitHub UI, look at the draft's assets, then **publish** the release. Publishing creates
   the tag `spinnaker-1.25.4`, and the tag push starts
   `.github/workflows/spinnaker-archive.yml`. The release must be published first, because the
   workflow downloads the assets with `gh release download`, which finds a release by tag only
   once it is published. **To run the workflow again** (after a fix on `main`, or if no run
   appeared), start it by hand with the release tag: Actions, spinnaker-archive, Run workflow,
   `release_tag` = `spinnaker-1.25.4`, or
   `gh workflow run spinnaker-archive.yml -f release_tag=spinnaker-1.25.4`. A run started by
   hand uses the workflow and scripts of the branch it is started on; the tag keeps pointing at
   the commit that was current when the release was published, so a tag-triggered run never
   sees later fixes. Pushes are idempotent (blobs already in the registry are skipped, manifests
   are put again with the same digests). For `spinnaker-1.25.4` the tag run failed at the push
   step (see "How the images are pushed") and pushed nothing; the run started by hand on `main`
   succeeded.
6. The workflow downloads the assets, checks the source bundle and the archives against the
   pins, pushes the five archive images and copies echo, runs
   `scripts/verify-spinnaker.py --blobs` (every manifest, config and layer byte against the
   pins), writes `published.yaml` and attaches it to the release. Watch the run. A file that does
   not match its pin fails the run before any push (the archive check step runs first); a
   manifest digest that differs from its pin fails that image before its upload, but images
   pushed earlier in the same run stay in the registry.
7. **Check the packages' visibility** (your profile, Packages: `spinnaker-clouddriver`,
   `-front50`, `-gate`, `-orca`, `-rosco`, `-echo`). The six packages created by the workflow in
   this public repository came up public without any UI step (anonymous `tags/list` answers 200
   for each); for a new package, confirm that, and if it is private use Package settings,
   Change visibility, Public. Also check that each package shows the repository as its source
   (the manifests carry the `org.opencontainers.image.source` annotation).
8. Check from a machine without credentials:
   `scripts/verify-spinnaker.py --blobs`, and
   `podman pull --platform linux/amd64 ghcr.io/aluminous/cloud-backports/spinnaker-gate@sha256:<digest from published.yaml>`.

**Alternative, manual route** (needs a personal token): a classic personal access token of the
publishing user with the `write:packages` scope (and `read:packages` to verify a private
package), passed as `REGISTRY_USERNAME` and `REGISTRY_PASSWORD` (or `REGISTRY_TOKEN`) in the
environment, or as a docker-style auth file (`docker login ghcr.io`, or `--auth-file`,
`REGISTRY_AUTH_FILE`; credential helpers are not supported, only the `auth` entry). Never on
the command line. Then, on the archive machine:

```bash
export ARCHIVES=/path/to/bundle-cache/<id>/images
scripts/push-spinnaker.py --archive-dir "$ARCHIVES" --convert-only    # checks everything, contacts no registry
scripts/push-spinnaker.py --archive-dir "$ARCHIVES" --result out/push.json
scripts/verify-spinnaker.py --blobs
scripts/write-published-spinnaker.py --result out/push.json           # published.yaml
```

The target namespace is `IMAGE_NAMESPACE` in `registry.env` (the workflow also honours the
repository variable of that name), or `--namespace`.

### How the images are pushed

For each archive image, one at a time, `push-spinnaker.py` checks the archive file's sha256, the
config digest (the image ID) and the layer count against the pins; hashes every layer and
compares it with its `diff_id`; builds the OCI manifest and compares its digest with the pin
(a mismatch aborts before any upload); uploads the layers, the config and then the manifest
(skipping blobs the repository already has); and checks that the registry reports the
pinned digest. The pushed layers are the archive's own uncompressed tars (media type
`application/vnd.oci.image.layer.v1.tar`) and the config is the archive's own config file, so
the registry holds the original image ID and diff_ids, and the manifest depends on nothing but
the archive. Each blob is streamed in one PATCH request, as container engines do; if a
registry refuses that, the script falls back to Content-Range chunks of 4 MiB, and
`SPINNAKER_UPLOAD_CHUNK=<bytes>` forces a chunk size. (ghcr.io answered HTTP 416 "request body
is too large" to 32 MiB chunks, and accepted the streamed request.)

Compressing the layers (gzip) was tried first and rejected: the same input and
level gave different bytes with classic zlib 1.2.12 (macOS) and zlib-ng 1.3.1 (Fedora's
Python 3.14), so a manifest digest could not be pinned across machines. The same manifest
digests came out of `--convert-only` on macOS (Python 3.15) and in the Podman machine
(Python 3.14). The cost is size, measured on the layer tars of the five archives (bytes):

| | uncompressed | gzip -6 | gzip -9 | zstd -3 | zstd -19 |
|---|---:|---:|---:|---:|---:|
| clouddriver | 1,598,008,320 | 828,719,135 | 826,592,735 | 789,077,151 | 711,558,335 |
| front50 | 313,355,264 | 175,300,578 | 174,917,294 | 165,320,050 | 151,060,155 |
| gate | 297,390,592 | 162,390,783 | 162,012,032 | 154,071,900 | 138,856,366 |
| orca | 323,401,728 | 184,668,365 | 184,283,559 | 175,971,236 | 159,476,797 |
| rosco | 568,941,056 | 223,521,210 | 222,380,035 | 206,171,732 | 177,019,996 |
| **total** | **3,101,096,960** | **1,574,600,071 (50.8%)** | **1,570,185,655 (50.6%)** | **1,490,612,069 (48.1%)** | **1,337,971,649 (43.1%)** |

(`scripts/measure-spinnaker-compression.py`; gzip with Python's zlib 1.2.12, zstd with Python
3.15's `compression.zstd` and 4 threads; the tar framing of the archives is not counted.)
ghcr.io accepts the uncompressed OCI layers, the docker-format config under the OCI manifest and
echo's docker v2 manifest unchanged. Pulling with Docker Engine, containerd or Kind nodes was
not tested; Podman 6.1 pulled gate and echo by digest from a local registry.

Echo is copied differently: `push-spinnaker.py` reads its manifest from `gcr.io` by the pinned
digest, checks that the bytes hash to that digest, downloads the config and every layer (each
hashed on the way), uploads them and puts the manifest byte for byte, so the copy has upstream's
own manifest digest (`sha256:6765ce1c…bdcd`), verifiable against gcr.io while it lasts. Its
layers stay gzip, as upstream serves them. `verify-spinnaker.py --blobs` gunzips each echo
layer and compares it with the config's `diff_id`.

The workflow (`.github/workflows/spinnaker-archive.yml`) runs only on the tag or by hand, never
for a pull request; permissions are `contents: write` (read assets, attach `published.yaml`)
and `packages: write`; its only third-party actions are `actions/checkout` and
`actions/upload-artifact`, pinned by SHA. The archives are read in place from the runner's
temporary directory (about 3.1 GB, plus the source bundle) and each blob is streamed to the
registry from the archive; echo's layers are spooled to a temporary file one at a time (largest
197 MB). It does not attest provenance: the images are not built in CI, and the pins are the
record.

### Dry run against a local registry

```bash
podman run -d --name backports-dryrun-registry -p 127.0.0.1:62925:5000 -v /var/lib/registry docker.io/library/registry:2
scripts/push-spinnaker.py --archive-dir "$ARCHIVES" --namespace 127.0.0.1:62925/cloud-backports --insecure
scripts/verify-spinnaker.py --namespace 127.0.0.1:62925/cloud-backports --insecure --blobs
podman pull --tls-verify=false --platform linux/amd64 127.0.0.1:62925/cloud-backports/spinnaker-gate@sha256:<manifest digest>
podman image inspect --format '{{.Id}}' <that reference>      # the pinned image ID
podman rm -f -v backports-dryrun-registry
```

Measured on 2026-11-14 (Apple Silicon, Podman 6.1.4, registry on loopback): all six images
(five from the archives, echo copied from gcr.io) pushed in 56 s into an empty repository path
(clouddriver 10 s, echo 36 s of downloading 426 MB), and again in 54 s into a second path with
the same digests; `verify-spinnaker.py --blobs` took 7.5 s; the pulled gate image reported the
pinned image ID `7c2e8142…5c00` and manifest digest `a4f9ebe8…e5da`, the pulled echo image the
pinned image ID `c6ca278c…0758` and upstream's manifest digest `6765ce1c…bdcd`. Over the
internet the time is the upload of 3.1 GB.

Before the release, every `run:` step of `spinnaker-archive.yml` was run locally in order
against the local registry (a directory of symlinks and a stub `gh` standing in for the release
assets). On GitHub, run 43545520704 (started by hand on `main` at 5ab773a with
`release_tag=spinnaker-1.25.4`) pushed or copied all six images with exactly the pinned digests
and passed `verify-spinnaker.py --blobs`; anonymous `verify-spinnaker.py` from a laptop passes
for all six.

### Source bundle

`scripts/build-spinnaker-sources.py` builds `spinnaker-1.25.4-sources.tar` from
[`images/spinnaker/1.25.4/packages.tsv`](images/spinnaker/1.25.4/packages.tsv), which
`scripts/inventory-spinnaker.py ARCHIVE... --packages-tsv` writes from the package databases of
the images (echo's archive is the old harness's copy of the image whose config digest is pinned).
Result of the run on 2026-11-14: 132 source packages (37 Alpine, 95 Debian: 82 with a GPL or
LGPL binary package and 13 whose licence could not be classified), 555 files, 668,078,080
bytes, sha256 `2526fc60…187a`, nothing missing; rebuilds from the cached downloads, and from a
bundle used as `--seed-from`, were byte-identical. `--seed-from OLD.tar` takes the packages
that are already in an earlier bundle from it (every file checked against the sha512 in its
MANIFEST) and downloads only the others; the second round of this bundle added the 13
Debian packages that way. Alpine files come from the aports repository at the recorded
commits (gitlab.alpinelinux.org API) and `distfiles.alpinelinux.org` or the upstream URL of the
APKBUILD, every source checked against the APKBUILD's sha512; Debian files come from
snapshot.debian.org, checked against its sha1 and the .dsc's sha256 (one component tarball of
perl, `perl_5.28.1.orig-regen-configure.tar.xz`, is stored in the snapshot under the name
`perl_5.28.0~rc1.orig-regen-configure.tar.xz`; the sha256 is the .dsc's). The bundle's own sha256
is pinned in `inputs.env`; it depends on the upstream files staying as they are, which the
per-file checksums enforce.

### Upstream check

Anonymous requests on 2026-11-14 (curl, no credentials, HTTP status of each; both registries
serve manifest and tag-list requests anonymously):

```
GET https://us-docker.pkg.dev/v2/spinnaker-community/docker/<service>/manifests/<tag>   -> 404 MANIFEST_UNKNOWN
    for clouddriver 7.3.3-20210322155326, front50 0.26.2-20210216140019, gate 1.21.0-20210215200018,
        orca 2.19.0-20210209140018, rosco 0.24.0-20210210110018
GET https://gcr.io/v2/spinnaker-marketplace/<service>/manifests/<tag>                   -> 404 MANIFEST_UNKNOWN (same five)
GET https://us-docker.pkg.dev/v2/spinnaker-community/docker/<service>/tags/list         -> 200 (clouddriver, front50, gate, orca, rosco, echo)
GET https://gcr.io/v2/spinnaker-marketplace/<service>/tags/list                         -> 200
GET https://gcr.io/v2/spinnaker-marketplace/echo/manifests/2.15.0-20201009170017        -> 200
    (Accept: application/vnd.docker.distribution.manifest.v2+json)
```

The `us-docker` tag lists contain none of the five tags and no 1.25.x tag (420 clouddriver,
278 front50, 359 gate, 356 orca and 285 rosco tags, of the 2025.0 and `spinnaker-1.37`/`1.38`
generations). The old harness recorded only tags and the archives' file hashes, not registry
digests, so there is no digest to try: pulling by digest could not be checked. Conclusion:
upstream does not serve the five, so the local archives are their only source and CI cannot
copy them registry to registry; the workflow therefore downloads them from a release.

Echo is the exception: `gcr.io/spinnaker-marketplace/echo:2.15.0-20201009170017` still
resolves (manifest `sha256:6765ce1c…bdcd`, config `sha256:c6ca278c…0758`, 10 gzip layers,
426,599,241 bytes), and is copied from there. It is the echo that the old harness's
real-Spinnaker run used, **not** release 1.25.4's echo (2.16.0-20210208200018, 404 at both
registries). A local archive of it exists outside the harness directories
(`mockyard/pocs/golden/out/images/echo-2.15.0-20201009170017.tar`, 760 MB, the image whose
config digest equals upstream's); it was only read, to list its packages for the source bundle.
