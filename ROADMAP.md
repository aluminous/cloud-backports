# Roadmap

## An arm64 Istio 1.10 gateway / sidecar (`proxyv2:1.10.6`)

Today Mockyard's arm64 lane runs a placeholder pod for the 1.10 ingress gateway: Gateway and
VirtualService objects, istiod validation and Argo Rollouts weight reconciliation are real,
ingress traffic is not proxied. A real gateway needs `proxyv2:1.10.6`, which contains two
amd64 binaries:

* **`pilot-agent`** (Go, Istio 1.10.6 source): easy, the same build as `pilot-discovery`
  (`./pilot/cmd/pilot-agent`, same toolchain, same ldflags). Under x86 emulation on arm64 the
  official one crashes in the Go 1.16 runtime (`lfstack.push invalid packing`).
* **`envoy`** (C++, Istio's Envoy fork `istio/proxy` at the commit pinned by 1.10.6's
  `istio.deps`, Envoy 1.18.x): the hard part. Upstream built it with Bazel in a pinned
  build image; an arm64 build of 2021 Envoy needs that Bazel version, a working clang/libc++
  toolchain for aarch64, and Istio's Wasm/extension build flags. Expect hours of compile time
  on a large runner and real porting work (Istio began publishing arm64 proxies only in 1.15).
  The 1.10 bootstrap template and Wasm extensions (`stats`, `metadata_exchange`) must match.

Intermediate idea (from the old harness's notes): **a hybrid image** with a native arm64
`pilot-agent` and the **official amd64 Envoy**, run under user-mode emulation. The old notes
saw the official Envoy start under emulation (`envoy --version` reports the expected build)
while `pilot-agent` crashed, so only the Go part needs rebuilding. Open questions before
publishing it: does Envoy under emulation actually serve xDS and route requests (must pass a
real request-routing test through a Gateway and VirtualService, not just `--version`); its
performance; and that it requires binfmt emulation on every node, which the official image
does not. It would be published clearly named (e.g. `istio-proxyv2-hybrid:1.10.6`), never
under the upstream name.

## The Spinnaker 1.25.4 service images archive: prepared for a public release, not published

**To publish** (nothing has been pushed anywhere; full steps in [BUILDING.md](BUILDING.md#spinnaker-1254-archive-publishing)):

1. Open owner todo: merge the branch, then run `scripts/create-spinnaker-release.sh --run` on the
   machine that holds the archives. It needs `gh` logged in with permission to create releases
   (a one-time upload of about 3.7 GB as release assets).
2. Publish the draft release in the GitHub UI: the new tag `spinnaker-1.25.4` starts the
   workflow, which pushes the images to GHCR with the job's own `GITHUB_TOKEN`.
3. In the GitHub package settings, set each new package public.

**No personal access token is needed** for this route. The alternative manual route
(`scripts/push-spinnaker.py` from the archive machine) needs a classic token with
`write:packages`; the token is deferred, so it is not the plan.

Mockyard's Spinnaker emulator is checked against golden captures from real Spinnaker
1.25.4. Upstream no longer serves those service images (the
`us-docker.pkg.dev/spinnaker-community/docker/*` tags are gone), so re-running a capture
depends on a local cache on the maintainer's machine (the old test harness's bundle cache),
which holds five of them as amd64 archives: clouddriver 7.3.3-20210322155326 (1.6 GB), rosco
0.24.0-20210210110018 (0.57 GB), orca 2.19.0-20210209140018 (0.32 GB), front50
0.26.2-20210216140019 (0.31 GB) and gate 1.21.0-20210215200018 (0.30 GB), about 3.1 GB in all.
A sixth image, echo 2.15.0-20201009170017 (the echo the capture run used, not the release's),
is still served by `gcr.io/spinnaker-marketplace` and is copied from there by digest.

This is **archiving, not backporting**: the same amd64 images, preserved; nothing rebuilt. They
are published as `spinnaker-<service>:<version>` with a `published.yaml` per release. Layers are
pushed uncompressed so that the manifest digests are reproducible from the archives; gzip
would cut the layer bytes by about half (3.10 GB to 1.57 GB at level 6 and 1.57 GB at level 9),
zstd by more (1.49 GB at level 3, 1.34 GB at level 19), but the compressed bytes depend on the
compressor implementation, so the digests could not be pinned across machines.

Licence position: Spinnaker is Apache-2.0, so redistribution of the services is allowed with
the licence. The images also contain Alpine Linux, Debian (echo), OpenJDK 11 and further tools
with their own licences, including GPL-2.0, GPL-3.0 and GPL-2.0-with-Classpath-exception
components, whose redistribution obliges offering the corresponding source. The packages are to
be public, so the corresponding source of the GPL/LGPL packages is prepared as a bundle
(`scripts/build-spinnaker-sources.py`) that is offered as a release asset next to the images;
the facts are in `images/spinnaker/1.25.4/NOTICE`. This is a working position, not legal advice.

An arm64 rebuild from source (Gradle, 2021 toolchains) would be a real backport and much more
work; amd64 under emulation was adequate for capture runs.
