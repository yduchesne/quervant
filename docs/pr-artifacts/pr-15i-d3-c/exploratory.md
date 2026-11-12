# PR 15I-D3-C exploratory four-arm diagnostic

> **EXPLORATORY_ONLY.** This is a non-official diagnostic run. It is **not**
> D3-C acceptance evidence and was not produced under a frozen T4. No policy
> was selected from it.

- Source BASE: `39dbd9f571a58bea8cc03d5a406533298e809bfe`
- Source experiment: `26681d3b7c12c7cca91f0c9139f73e2dac8b09e5`
- BASE binary SHA-256: `3e3755c9dc73fbf99385e438d0a988bbfde9a3f39f4dae9d83e34eb36529a671`
- Experiment binary SHA-256: `258e6d59a5880870bc600216f4fda880d9b4126c98c165c48c43f9f96bf27aaf`
- Adapter feature argv: `['cargo', 'build', '--release', '--locked', '--manifest-path', '/home/yduchesne/Dev/Github/yduchesne/quervant/benchmarks/pr15d/adapters/quervant/Cargo.toml', '--target-dir', '/home/yduchesne/Dev/Github/yduchesne/quervant/target/pr15i-d3-c/explore-01/build/B', '--features', 'quervant-core/pr15i-d3c-experiment']`
- Index: 100000 docs, digest `5734ae60591f7563b89d74cfbaedb8d856ae0db6aeb3e7d9bcbb9218966b7789`
- Lanes: 8, balanced rounds: 4, samples/lane: 20
- Host readiness: `READY`; failure codes: `[]`
- Every sample was checked against the independent PR15D oracle before timing was accepted.

| K | class | BASE ns | linear ns | linear % | P2 ns | P2 % | exact_set ns | exact_set % |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 10 | medium | 15521653 | 15749644 | +1.47% | 15447535 | -0.48% | 15549642 | +0.18% |
| 100 | medium | 18520405 | 18633670 | +0.61% | 15422039 | -16.73% | 15521233 | -16.19% |
| 256 | medium | 23883014 | 24217370 | +1.40% | 15781435 | -33.92% | 15824435 | -33.74% |
| 1024 | medium | 55308594 | 56010621 | +1.27% | 18485271 | -66.58% | 16883756 | -69.47% |
| 10 | common | 33621100 | 33929201 | +0.92% | 33517309 | -0.31% | 33695609 | +0.22% |
| 100 | common | 44708367 | 45423961 | +1.60% | 33559893 | -24.94% | 34283446 | -23.32% |
| 256 | common | 65642197 | 66803698 | +1.77% | 33767142 | -48.56% | 33686310 | -48.68% |
| 1024 | common | 183380747 | 188227586 | +2.64% | 42769188 | -76.68% | 35062107 | -80.88% |
