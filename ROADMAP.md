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

## The Spinnaker 1.25.4 service images archive: prepared, not published

Mockyard's Spinnaker emulator is checked against golden captures from real Spinnaker
1.25.4. Upstream no longer serves those service images (the `us-docker.pkg.dev/spinnaker-community/docker/*`
tags are gone), so re-running a capture depends on a local cache on the maintainer's machine
(the old test harness's bundle cache), which holds five of them as amd64 archives: clouddriver
7.3.3-20210322155326 (1.6 GB), rosco 0.24.0-20210210110018 (0.57 GB), orca 2.19.0-20210209140018
(0.32 GB), front50 0.26.2-20210216140019 (0.31 GB) and gate 1.21.0-20210215200018 (0.30 GB),
about 3.1 GB in all.

State: **prepared, not pushed anywhere.** The pins (`images/spinnaker/1.25.4/inputs.env`), the
push and verify scripts, the provenance `NOTICE` and the documentation are in place, and the
scripts have been run against a throwaway local registry ([BUILDING.md](BUILDING.md#spinnaker-1254-archive-publishing)).
This is **archiving, not backporting**: the same amd64 images, preserved; nothing rebuilt. They
would be published as `spinnaker-<service>:<version>` with a `published.yaml` per release. There
is no workflow: upstream no longer serves the images, so CI has no source to copy from, and the
publish is a manual run on the machine that holds the archives.

Licence position: Spinnaker is Apache-2.0, so redistribution of the services is allowed with the
licence. The images also contain Alpine Linux, Alpine's OpenJDK 11 and further tools with their
own licences, including GPL-2.0, GPL-3.0 and GPL-2.0-with-Classpath-exception components, whose
redistribution obliges offering the corresponding source. The facts (versions, where the source
for each package is available) are in `images/spinnaker/1.25.4/NOTICE`; this repository does not
host that source. Until the obligation is met in a way the owner accepts, the packages are best
kept private to the organisation.

Open decisions for the owner before anything is pushed:

* Public or private package? Public needs the source offer settled (host the source of the
  GPL packages next to the images, or keep the packages private).
* Whether to add echo, which the old real-Spinnaker capture used as
  `gcr.io/spinnaker-marketplace/echo:2.15.0-20201009170017` (not the release's echo, 2.16.0). It is
  still served upstream by digest, so it could be copied registry to registry in CI instead of
  archived.
* Whether to publish with compressed layers (about half the size on the wire and in storage,
  but the digests then depend on the compressor), or as pinned now (uncompressed layers).

An arm64 rebuild from source (Gradle, 2021 toolchains) would be a real backport and much more
work; amd64 under emulation was adequate for capture runs.
