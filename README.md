# cloud-backports

Container images of older cloud-infrastructure releases that upstream never published, or no
longer publishes, kept runnable for testing against platforms that still run them.

- **arm64 backports:** images upstream never published for **linux/arm64**, built from the
  exact upstream release source with pinned inputs, so old platform versions run natively on
  Apple Silicon and arm64 CI. Each is published under one multi-arch tag: arm64 is built here,
  amd64 is upstream's official image carried over by digest (not rebuilt).
- **Archives (planned):** upstream images that have disappeared from their registries, such as
  the Spinnaker 1.25.4 services, preserved unmodified. See [ROADMAP.md](ROADMAP.md).

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
GitHub release. Nothing has been published yet.

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
compare. Provenance attestations (GitHub artifact attestations) are pushed with each image once this
repository is public (GitHub does not offer them for user-owned private repositories, so the
workflow skips that step while it is private):
`gh attestation verify oci://<reference> --owner aluminous`. The amd64 half is upstream's
own manifest: compare its digest with `docker.io/istio/pilot:1.10.6` (`crane digest
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
  module_tar.py                      save the Go module set as a deterministic tar
.github/workflows/istio-pilot.yml    CI: build on arm64, verify, push, index, attest, record
```

## CI

`.github/workflows/istio-pilot.yml` builds on a native arm64 runner (`ubuntu-24.04-arm`),
runs the verification, and only on a tag `istio-pilot-1.10.6*` or a manual run pushes
`istio-pilot:1.10.6-arm64`, assembles `istio-pilot:1.10.6`, attests provenance for both (public repository only), and
attaches `published.yaml`, the digests of what was published, to the release. Pull
requests build and verify but never push. Token permissions are per job and minimal;
actions are pinned by commit SHA. **The workflow has been linted (actionlint, shellcheck) but
has not run yet.**

## Licences

The scripts and docs of this repository: MIT ([LICENSE](LICENSE)). The images contain
upstream software under its own licences: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
