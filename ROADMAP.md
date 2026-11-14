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

## Spinnaker 1.25.4 archive: what is still open

The archive is published ([README.md](README.md#spinnaker-1254-archive), [BUILDING.md](BUILDING.md#spinnaker-1254-archive-publishing)):
five service images of release 1.25.4, the echo that the capture run used, and the source
bundle. Still open:

* **Other services of release 1.25.4 are not archived** (deck, fiat, igor, kayenta, the
  monitoring services) and neither is the release's own echo, 2.16.0-20210208200018: none is in
  the local archives and no registry serves them. The archived echo is 2.15.0-20201009170017.
* **Clients not tested.** The packages were checked through the registry API (manifest,
  config, diff_ids, every layer) and with Podman against a local registry, not pulled by Docker
  Engine, containerd or Kind nodes, and the containers were not run.
* **Compression trade-off.** Layers are stored uncompressed (3.10 GB) so that manifest digests
  are reproducible. gzip would cut the layer bytes to 1.57 GB (level 6 or 9), zstd to 1.49 GB
  (level 3) or 1.34 GB (level 19), but the compressed bytes depend on the compressor
  implementation, so the digests could not be pinned across machines. A change would mean new
  digests and a new pinned release.
* **No arm64 build.** An arm64 rebuild from source (Gradle, 2021 toolchains) would be a real
  backport and much more work; amd64 under emulation was adequate for capture runs.
