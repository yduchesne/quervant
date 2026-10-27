#!/usr/bin/env python3
"""SR-14F-01 source-order regression for the remote pre-cold oracle.

The check is deliberately anchored inside the remote ``runtime.block_on`` block
so a local-cold W09 oracle or the later remote-warm oracle cannot satisfy it.
These source checks supplement, and never replace, the runtime marker/assert and
the real-RustFS qualified campaign.
"""
import unittest
from pathlib import Path

COLD = "let mut cold = Vec::with_capacity(SAMPLES);"
PRE = "correctness(&validation_snapshot);"
MARKER = "PR14F_REMOTE_ORACLE_BEFORE_COLD=PASS"
FLAG = "assert!(remote_oracle_passed);"
POST = "correctness(&snapshot);"
END = 'let raw = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))'


def remote_block(source):
    start = source.index("runtime.block_on(async {")
    end = source.index(END, start)
    return source[start:end]


def check_order(source):
    errors = []
    try:
        block = remote_block(source)
    except ValueError as error:
        return [f"remote block boundaries not found: {error}"]

    cold = block.find(COLD)
    pre = block.find(PRE)
    marker = block.find(MARKER)
    flag_any = block.find(FLAG)
    flag_loop = block.find(FLAG, cold) if cold >= 0 else -1
    post = block.find(POST)
    if cold < 0:
        errors.append("remote cold loop not found")
    if pre < 0:
        errors.append("pre-cold validation oracle not found")
    if marker < 0:
        errors.append("pre-cold marker not found")
    if flag_any < 0:
        errors.append("oracle-passed assertion not found")
    if post < 0:
        errors.append("post-cold warm-boundary oracle not found")
    if cold >= 0 and pre >= 0 and pre > cold:
        errors.append("pre-cold oracle appears after the remote cold loop")
    if cold >= 0 and marker >= 0 and marker > cold:
        errors.append("marker appears after the remote cold loop")
    if pre >= 0 and marker >= 0 and marker < pre:
        errors.append("marker appears before the oracle returns")
    if marker >= 0 and flag_any >= 0 and flag_any > marker:
        errors.append("oracle-passed assertion appears after the marker")
    if cold >= 0 and post >= 0 and post < cold:
        errors.append("post-cold oracle appears before the cold loop")

    if cold >= 0:
        first_instant = block.find("Instant::now()", cold)
        per_sample_reset = block.find(
            "let _ = std::fs::remove_dir_all(&workspace);", cold
        )
        if first_instant < 0:
            errors.append("timed Instant::now() not found after the cold loop")
        if per_sample_reset < 0:
            errors.append("per-sample workspace reset not found after the cold loop")
        if first_instant >= 0 and marker >= 0 and marker > first_instant:
            errors.append("marker appears after the first cold stopwatch")
        if first_instant >= 0 and flag_loop >= 0 and not (cold < flag_loop < first_instant):
            errors.append("oracle-passed assertion is not inside the cold loop")
        if flag_loop < 0:
            errors.append("cold loop is missing assert!(remote_oracle_passed)")
    return errors


class OracleOrderTests(unittest.TestCase):
    def test_real_remote_block_passes(self):
        source = Path(__file__).resolve().parent.parent.parent.joinpath(
            "crates/quervant-core/tests/pr14_bench_remote.rs"
        ).read_text(encoding="utf-8")
        self.assertEqual(check_order(source), [])

    def test_baseline_ordering_is_rejected(self):
        baseline = f"""
runtime.block_on(async {{
    let mut cold = Vec::with_capacity(SAMPLES);
    for sample in 0..SAMPLES {{
        let _ = std::fs::remove_dir_all(&workspace);
        let start = Instant::now();
    }}
    let reader = RemoteIndex::open_existing(...).await.unwrap();
    let snapshot = reader.snapshot();
    correctness(&snapshot);
    {END};
}});
"""
        errors = check_order(baseline)
        self.assertTrue(errors)
        self.assertTrue(any("pre-cold" in error or "marker" in error for error in errors))

    def test_local_w09_oracle_does_not_satisfy_remote(self):
        source = f"""
correctness(&local_snapshot);
runtime.block_on(async {{
    let mut cold = Vec::with_capacity(SAMPLES);
    for sample in 0..SAMPLES {{
        let _ = std::fs::remove_dir_all(&workspace);
        let start = Instant::now();
    }}
    {END};
}});
"""
        errors = check_order(source)
        self.assertTrue(any("pre-cold" in error for error in errors))

    def test_corrected_synthetic_block_passes(self):
        corrected = f"""
runtime.block_on(async {{
    let mut remote_oracle_passed = false;
    {{
        let validation_snapshot = index.snapshot();
        {PRE}
        remote_oracle_passed = true;
    }}
    drop(index);
    match std::fs::remove_dir_all(&workspace) {{
        Ok(()) => (),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => (),
        Err(error) => panic!("remote oracle cache reset failed: {{error}}"),
    }}
    assert!(remote_oracle_passed);
    println!("{MARKER}");
    let mut cold = Vec::with_capacity(SAMPLES);
    for sample in 0..SAMPLES {{
        assert!(remote_oracle_passed);
        let _ = std::fs::remove_dir_all(&workspace);
        let start = Instant::now();
    }}
    let reader = RemoteIndex::open_existing(...).await.unwrap();
    let snapshot = reader.snapshot();
    {POST}
    {END};
}});
"""
        self.assertEqual(check_order(corrected), [])

    def test_marker_after_cold_is_rejected(self):
        source = f"""
runtime.block_on(async {{
    let mut remote_oracle_passed = true;
    {PRE}
    let mut cold = Vec::with_capacity(SAMPLES);
    for sample in 0..SAMPLES {{
        assert!(remote_oracle_passed);
        let _ = std::fs::remove_dir_all(&workspace);
        let start = Instant::now();
    }}
    println!("{MARKER}");
    {POST}
    {END};
}});
"""
        self.assertTrue(any("marker" in error for error in check_order(source)))

    def test_missing_assert_is_rejected(self):
        source = f"""
runtime.block_on(async {{
    {PRE}
    println!("{MARKER}");
    let mut cold = Vec::with_capacity(SAMPLES);
    for sample in 0..SAMPLES {{
        let _ = std::fs::remove_dir_all(&workspace);
        let start = Instant::now();
    }}
    {POST}
    {END};
}});
"""
        self.assertTrue(any("assertion" in error for error in check_order(source)))


if __name__ == "__main__":
    unittest.main()
