# Third-party notices

The scripts and documentation of this repository are MIT-licensed ([LICENSE](LICENSE)). The
**images** it publishes contain third-party software under its own licences:

| Image | Contains | Licence | Where the texts are |
|---|---|---|---|
| `istio-pilot:1.10.6` (linux/arm64) | `pilot-discovery` compiled without modification from Istio 1.10.6 (<https://github.com/istio/istio>, revision `fd053c6165d21105d66dac6e3d0649db2dde5b86`), Copyright Istio Authors | Apache-2.0 | in the image: `/usr/share/doc/istio-pilot/LICENSE`, `NOTICE`; here: [`LICENSES/Apache-2.0.txt`](LICENSES/Apache-2.0.txt) (Istio's own `LICENSE` file, verbatim) |
| | the Go modules statically linked into it | their own licences (Apache-2.0, BSD, MIT, MPL-2.0, ...) | in the image: `/usr/share/doc/istio-pilot/licenses/` (the `licenses/` folder of the Istio source archive, as Istio ships it) |
| | the base image `gcr.io/distroless/static-debian12:nonroot` (CA certificates, tzdata, `/etc/passwd`) | Debian package licences | in the image: `/usr/share/doc/*/copyright` (from the base) |
| `istio-pilot:1.10.6` (linux/amd64) | upstream's official image `docker.io/istio/pilot:1.10.6`, unchanged | as upstream | as upstream |

Apache-2.0 section 4 obligations for the redistributed binary: the licence text travels with
it (above); Istio 1.10.6 has no `NOTICE` file, so there is none to carry over; the image's
`NOTICE` says what was done (compiled for another architecture, no source change) and that
this is not an official Istio release. "Istio" is a trademark of its owners and is used here
only to identify the upstream software.

The Istio source archive itself is not redistributed by this repository: the build downloads
it from GitHub and checks its sha256.
