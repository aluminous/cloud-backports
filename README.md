# cloud-backports

Container images of older cloud-infrastructure releases that upstream never published, or no
longer publishes, kept runnable for testing against platforms that still run them.

- **arm64 backports:** images upstream never published for **linux/arm64**, built from the
  exact upstream release source with pinned inputs, so old platform versions run natively on
  Apple Silicon and arm64 CI. Each is published under one multi-arch tag: arm64 is built here,
  amd64 is upstream's official image carried over by digest (not rebuilt).
- **Archives (prepared, not published):** upstream images that have disappeared from their
  registries, preserved unmodified: the five Spinnaker 1.25.4 service images
  (`spinnaker-<service>`, linux/amd64). See [Spinnaker 1.25.4 archive](#spinnaker-1254-archive).

**What this is:** reproducible rebuilds of unmodified upstream release source, verified
against pinned hashes, with the upstream licences inside the image.
**What this is not:** an official release of any upstream project, a fork, or a patched
version. Nothing here is endorsed by the upstream projects. No new features, no security
fixes: these are old versions, kept runnable for testing against platforms that still run
them.

First consumer: Mockyard's legacy lane (Kubernetes
1.21, Istio 1.10.6, Argo Rollouts 1.4.1), which used to compile the pilot itself.

## Images

The registry namespace is one variable, `IMAGE_NAMESPACE` in [`registry.env`](registry.env)
(default `ghcr.io/aluminous/cloud-backports`; the workflow also honours a repository
variable of the same name).

| Image | Upstream | linux/arm64 | linux/amd64 | Differences from upstream |
|---|---|---|---|---|
| `istio-pilot:1.10.6` | `docker.io/istio/pilot:1.10.6`, Istio 1.10.6, revision `fd053c6165d21105d66dac6e3d0649db2dde5b86` | built here from the release source with Go 1.16.9 and the release ldflags; binary sha256 `b851b0b5af62ea9b57f2ef51b5c7ee31e624d6e4c1f06a3892c5acb778973c44` | upstream image `sha256:689e4fcd118e281ad793c39326562bef63d5a2301dbe0281625a6e64022e19eb`, byte for byte | arm64 only: base `gcr.io/distroless/static-debian12:nonroot` (pinned) instead of Istio's Ubuntu base (no shell, no apt); licences of Istio and of every linked Go module in `/usr/share/doc/istio-pilot/`; OCI labels. Same path (`/usr/local/bin/pilot-discovery`), entrypoint (no `Cmd`), user `1337:1337`, working directory `/`, no exposed ports and no volumes, as upstream, which is what the 1.10 istiod chart relies on (it mounts only Secret/emptyDir/token volumes under `/var/run/secrets/` and `/etc/cacerts`). Env: upstream sets `DEBIAN_FRONTEND=noninteractive`, this image `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt` (from the base); both have the same `PATH`. Upstream has `/bin/sh` and Ubuntu tools for `kubectl exec` debugging; this image has no shell. |

Other legacy images that upstream has for amd64 only, and their status:

| Upstream image | Status |
|---|---|
| `docker.io/istio/proxyv2:1.10.6` (sidecar and ingress gateway) | **not provided.** It needs an arm64 Envoy 1.18 as well as `pilot-agent`; see [ROADMAP.md](ROADMAP.md). Mockyard runs a selector-compatible placeholder pod (from an image it already has) for the 1.10 ingress gateway on arm64, so a placeholder image here would not remove anything the harness builds; none is published. |
| `docker.io/istio/pilot:1.10.6` | this repository (above) |

Not needed: `kindest/node:v1.21.14` and `quay.io/argoproj/argo-rollouts:v1.4.1` already
publish arm64.

The published digests of every release are in the `published.yaml` file attached to that
GitHub release.

## Spinnaker 1.25.4 archive

Prepared, **not published**: nothing has been pushed anywhere, and nothing is published until
the owner decides (see [ROADMAP.md](ROADMAP.md) for the open decisions). The images are
upstream's own, saved from `us-docker.pkg.dev/spinnaker-community/docker/` before the tags
were removed (on 2026-11-14 they no longer resolve there or at `gcr.io/spinnaker-marketplace`,
[BUILDING.md](BUILDING.md#upstream-check)). Nothing is rebuilt or modified: each image keeps
its original configuration (its image ID) and every layer byte for byte. All are
linux/amd64, `docker-archive` format source, Alpine Linux base, Alpine's OpenJDK 11.

| Image (as it would be published) | Original reference | Archive | Image ID (config digest) | Layers | Base | JVM |
|---|---|---|---|---|---|---|
| `spinnaker-clouddriver:7.3.3-20210322155326` | `us-docker.pkg.dev/spinnaker-community/docker/clouddriver:7.3.3-20210322155326` | 1,598,071,296 bytes, sha256 `39914318…f0ea` | `sha256:48a25fb6fb34…c3b8` | 14 | Alpine 3.12.4 | OpenJDK 11.0.9 |
| `spinnaker-front50:0.26.2-20210216140019` | `…/front50:0.26.2-20210216140019` | 313,381,888 bytes, sha256 `654972c7…2950` | `sha256:7c65eaab9171…001b` | 6 | Alpine 3.11.7 | OpenJDK 11.0.5 |
| `spinnaker-gate:1.21.0-20210215200018` | `…/gate:1.21.0-20210215200018` | 297,417,216 bytes, sha256 `8054ea1a…5825` | `sha256:7c2e8142a3c3…5c00` | 6 | Alpine 3.11.7 | OpenJDK 11.0.5 |
| `spinnaker-orca:2.19.0-20210209140018` | `…/orca:2.19.0-20210209140018` | 323,428,352 bytes, sha256 `0ba1e1a8…1ff7` | `sha256:13efa8585e46…e1b2` | 6 | Alpine 3.11.7 | OpenJDK 11.0.5 |
| `spinnaker-rosco:0.24.0-20210210110018` | `…/rosco:0.24.0-20210210110018` | 568,989,696 bytes, sha256 `3f51c52e…ea09` | `sha256:f12a552b5f96…841c` | 12 | Alpine 3.12.3 | OpenJDK 11.0.9 |

The full values (file sha256, image ID, manifest digest) are pinned in
[`images/spinnaker/1.25.4/inputs.env`](images/spinnaker/1.25.4/inputs.env); the licence and
source facts are in [`images/spinnaker/1.25.4/NOTICE`](images/spinnaker/1.25.4/NOTICE). Not
included, because they are not in the local archives: echo, deck, fiat, igor, kayenta and
the monitoring services of release 1.25.4 (the old harness's real-Spinnaker run also used
echo `2.15.0-20201009170017`, which is not the release's echo and is still served by
`gcr.io/spinnaker-marketplace`; see [BUILDING.md](BUILDING.md#upstream-check)).

The pushed manifest is an OCI manifest over the original, uncompressed layers, so its digest
depends on nothing but the archive and is pinned too. Once published, pin by digest as for
istio-pilot (`ghcr.io/aluminous/cloud-backports/spinnaker-gate@sha256:<digest>` from
`published.yaml`); to check a published copy against the pins:

```bash
scripts/verify-spinnaker.py                    # manifest, config and diff_ids from the registry
scripts/verify-spinnaker.py --blobs            # also download and hash every layer (3.1 GB)
```

Publishing needs the local archives: [BUILDING.md](BUILDING.md#spinnaker-1254-archive-publishing).
These are 2021 images with unmaintained components; use them for tests only.

## Pull

```bash
NS=ghcr.io/aluminous/cloud-backports
docker pull $NS/istio-pilot:1.10.6                  # the right architecture for this machine
podman pull --platform linux/arm64 $NS/istio-pilot:1.10.6
```

**Pin by digest, never by tag.** Take `pinned` from the release's `published.yaml`, e.g.
`ghcr.io/aluminous/cloud-backports/istio-pilot:1.10.6@sha256:<index digest>`, or a single
platform's digest from its `platforms` map. The tag may be re-pointed if the image is rebuilt
(for example after a base image update); a digest never changes. For Helm with the 1.10
chart: `--set pilot.image=<pinned reference>` (a value containing `/` is used as is), and leave
`global.hub`/`global.tag` alone so sidecar injection keeps the official proxy image.

## Mirror into another registry

All of these copy the whole index (both platforms) and keep the digests:

```bash
SRC=ghcr.io/aluminous/cloud-backports/istio-pilot@sha256:<index digest>
DST=registry.corp.example/mirror/istio-pilot:1.10.6
skopeo copy --all docker://$SRC docker://$DST
crane copy $SRC $DST
docker buildx imagetools create --tag $DST $SRC
regctl image copy $SRC $DST
```

`docker pull` + `docker push` copies one platform only; avoid it for mirroring.

**Across an air gap** (one file, digests preserved):

```bash
skopeo copy --all docker://$SRC oci-archive:istio-pilot-1.10.6.oci.tar   # online side
sha256sum istio-pilot-1.10.6.oci.tar > istio-pilot-1.10.6.oci.tar.sha256
skopeo copy --all oci-archive:istio-pilot-1.10.6.oci.tar docker://$DST    # offline side
# or: crane pull --format=oci $SRC dir/ ; crane push dir/ $DST
```

Mockyard users can also carry it inside a Mockyard bundle (`mockyard bundle export`), which
pins and verifies it like every other image.

## Verify an image against the pinned inputs

```bash
scripts/verify-image.sh --pull ghcr.io/aluminous/cloud-backports/istio-pilot@sha256:<arm64 digest>
```

checks the image config (user, entrypoint, working directory), that the binary's sha256 is
`BINARY_SHA256_ARM64` from [`images/istio-pilot/1.10.6/inputs.env`](images/istio-pilot/1.10.6/inputs.env),
and that `pilot-discovery version` reports 1.10.6, the upstream revision, `Clean` and
`go1.16.9`. The binary is reproducible: rebuild it yourself ([BUILDING.md](BUILDING.md)) and
compare. Each published image (the index and the arm64 image) carries a GitHub build-provenance
attestation, signed by the CI run that built it. Verify it with
`gh attestation verify oci://ghcr.io/aluminous/cloud-backports/istio-pilot@sha256:<digest> --owner aluminous`
(the workflow skips the attestation steps only while the repository is private, because GitHub
does not offer them there). The amd64 half is upstream's
own manifest, with no attestation here: compare its digest with `docker.io/istio/pilot:1.10.6` (`crane digest
--platform linux/amd64 docker.io/istio/pilot:1.10.6`).

## Repository layout

```
registry.env                         IMAGE_NAMESPACE: the one place to change the registry
images/istio-pilot/1.10.6/
  inputs.env                         every pin: source, revision, Go builder, base, outputs
  Containerfile                      packaging of the verified binary
  NOTICE                             shipped in the image next to Istio's LICENSE
scripts/
  build-istio-pilot.sh               compile in the pinned Go container, verify, stage context
  image-build.sh                     build the arm64 image from that context
  verify-image.sh                    check an image against the pins
  assemble-index.sh                  publish the multi-arch tag (arm64 here + amd64 upstream)
  write-published.py                 write published.yaml, the digests attached to a release
  push-spinnaker.py                  verify the Spinnaker archives against the pins, push them
  verify-spinnaker.py                check pushed Spinnaker images against the pins (registry API)
  write-published-spinnaker.py       add the Spinnaker images to published.yaml
  inventory-spinnaker.py             read facts (config, OS, JVM, packages) out of the archives
  spinnaker_archive.py               shared code: archive reader, registry client
  module_tar.py                      save the Go module set as a deterministic tar
images/spinnaker/1.25.4/
  inputs.env                         pins: archive sha256, image ID, manifest digest per service
  NOTICE                             provenance, licence and source facts
.github/workflows/istio-pilot.yml    CI: build on arm64, verify, push, index, attest, record
```

## CI

`.github/workflows/istio-pilot.yml` builds on a native arm64 runner (`ubuntu-24.04-arm`),
runs the verification, and only on a tag `istio-pilot-1.10.6*` or a manual run pushes
`istio-pilot:1.10.6-arm64`, assembles `istio-pilot:1.10.6`, attests provenance for both (public repository only), and
attaches `published.yaml`, the digests of what was published, to the release. Pull
requests build and verify but never push. Token permissions are per job and minimal;
actions are pinned by commit SHA.

## Licences

The scripts and docs of this repository: MIT ([LICENSE](LICENSE)). The images contain
upstream software under its own licences: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
