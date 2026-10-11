# Licensing

Trawler is a **mixed-license monorepo**. Repository visibility does not imply every component is open source under the OSI definition.

| Scope | SPDX identifier | Terms |
| --- | --- | --- |
| `crates/trawler-core/**` | `Apache-2.0` | [Apache License 2.0](LICENSES/Apache-2.0.txt) |
| `crates/trawler-objectstore/**` | `Apache-2.0` | [Apache License 2.0](LICENSES/Apache-2.0.txt) |
| `crates/trawler-distributed/**` | `Elastic-2.0` | [Elastic License 2.0](LICENSES/Elastic-2.0.txt) |
| Future Coordinator, Aggregator, and Search Node services | Intended `Elastic-2.0` | To be declared in their manifests when added |

Top-level repository documentation and configuration are provided for project use; do not infer a license grant for a particular software component from their location. Source-file license headers may be added as implementation grows.

Apache-2.0 permits commercial use and proprietary integration subject to its terms. Elastic License 2.0 is source-available, **not OSI open source**, and includes restrictions on offering the licensed product as a managed service, circumventing license keys, and removing licensing notices.

The core's permissive license does not prevent independent implementations of distributed search based on the core. No dual-licensing or contributor relicensing program has been adopted. Consult the actual license texts for authoritative terms and obtain legal review before commercial distribution.
