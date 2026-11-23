"""PERF-02-B diagnostic helper: deterministic, fully mocked, never timed in CI.

The module under test is a measurement *helper*. These tests therefore never run
``quervant-bench run``, a third-party engine, ``perf record``, real timing or a
production Cargo build: adapter replies and ``perf script`` captures are pure
Python fixtures (see T12).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from quervant_bench.lean import artifacts, configuration, runtime
from quervant_bench.lean import perf02b_diagnostics as diag

BASE = "c" * 40
CONFIG_NAME = "perf02b-diagnostics"


def _write(tmp_path: Path, config: dict) -> Path:
    return artifacts.create_configuration(
        artifacts.configuration_directory(tmp_path / "benchmarks" / "studies", config), config
    )


def _valid(tmp_path: Path, *, name: str = CONFIG_NAME) -> tuple[Path, dict]:
    config = configuration.default_configuration(
        "perf-02", name, "PERF-02-B diagnostic fixture",
        timestamp="2026-11-22T10:00:00Z", regime="warm",
        baseline_revision=BASE, candidate_revision=BASE,
    )
    return _write(tmp_path, config), config


def _mutated(tmp_path: Path, mutate, *, name: str) -> Path:
    """Write a deliberately invalid configuration without the strict factory."""
    config = configuration.default_configuration(
        "perf-02", name, "PERF-02-B mutated fixture",
        timestamp="2026-11-22T10:00:00Z", regime="warm",
        baseline_revision=BASE, candidate_revision=BASE,
    )
    mutate(config)
    directory = tmp_path / "benchmarks" / "studies" / "perf-02" / "warm" / "configurations"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / artifacts.configuration_filename(config)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _lanes(config: dict) -> dict[str, dict]:
    return {lane["id"]: lane for lane in configuration.lanes_for(config)}


def _encode(rows) -> str:
    return "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)


def _reply(config: dict, row: dict) -> dict:
    """Synthetic, oracle-correct Quervant adapter reply (no engine is executed)."""
    phase, lane_id, kind, index = diag._parse_request_id(row["request_id"])
    lane = _lanes(config)[lane_id]
    total, doc_ids = runtime.expected_answer(lane["n"], row["field"], row["term"], row["k"])
    engine_ns = 500_000_000 if kind == "warmup" else 1_000_000 + index * 1_000
    return {"schema": "pr15d-adapter-v1", "engine": "quervant", "status": "ok",
            "request_id": row["request_id"], "total_hits": total,
            "doc_ids": doc_ids, "engine_ns": engine_ns}


def _replies(config: dict, rows) -> list[dict]:
    return [_reply(config, row) for row in rows]


def _write_responses(out: Path, filename: str, rows) -> Path:
    path = out / "responses" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_encode(rows), encoding="utf-8", newline="\n")
    return path


def _perf_record(symbols, *, comm="pr15d-quervant", event="cpu-clock:u",
                 dso="/tmp/build/pr15d-quervant-adapter") -> str:
    lines = [f"{comm}  4242/4242  1234.567890: {event}: "]
    for index, symbol in enumerate(symbols):
        lines.append(f"\t    {0x1000 + index:016x} {symbol} ({dso})")
    return "\n".join(lines) + "\n\n"


def _default_script(queries: int = 450, startup: int = 10) -> str:
    sort_sample = ["UnifiedSearcher::search", "UnifiedSearcher::collect_mixed",
                   "consider_borrowed_keyword_candidate", "keyword_sort_view"]
    startup_sample = ["std::rt::lang_start", "__libc_start_main"]
    return (_perf_record(sort_sample) * queries) + (_perf_record(startup_sample) * startup)


def _campaign(tmp_path: Path, *, script: str | None = None) -> tuple[Path, Path, dict]:
    """inputs -> synthetic replies -> verified summaries -> synthetic perf captures."""
    config_path, config = _valid(tmp_path)
    out = tmp_path / "target" / "perf02b"
    diag.generate_inputs(config_path, out)
    for request_file in sorted((out / "requests").glob("*.jsonl")):
        rows = diag._read_jsonl(request_file)
        response_file = _write_responses(out, request_file.name, _replies(config, rows))
        diag.verify_stream(config_path, request_file, response_file,
                           out / "validated" / f"{request_file.stem}.json")
    for slug, _lane_id in diag.PRIMARY_LANES:
        (out / f"{slug}.perf-script.txt").write_text(script if script is not None else _default_script(),
                                                    encoding="utf-8")
        (out / f"{slug}.perf-report.txt").write_text("# perf report context\n", encoding="utf-8")
    return config_path, out, config


# --------------------------------------------------------------------------- #
# T01 - T04: deterministic request streams
# --------------------------------------------------------------------------- #


def test_t01_valid_a_equal_a_configuration_yields_six_streams_and_16_lanes(tmp_path):
    config_path, config = _valid(tmp_path)
    result = diag.generate_inputs(config_path, tmp_path / "target" / "perf02b")
    files = sorted(Path(result["directory"]).glob("*.jsonl"))
    assert [path.name for path in files] == [
        "baseline-n10000.jsonl", "baseline-n100000.jsonl",
        "profile-n100000-common-k10.jsonl", "profile-n100000-common-k100.jsonl",
        "profile-n100000-medium-k10.jsonl", "profile-n100000-medium-k100.jsonl",
    ]
    manifest = json.loads((Path(result["directory"]) / "inputs-manifest.json").read_text())
    assert manifest["schema"] == diag.INPUTS_MANIFEST_SCHEMA
    assert manifest["source_revision"] == BASE
    assert manifest["configuration_id"] == config["configuration_id"]
    assert manifest["timed_campaign"] is False
    assert manifest["benchmark_result_v1"] is False
    assert len(manifest["lane_ids"]) == 16
    assert len(set(manifest["lane_ids"])) == 16
    assert manifest["primary_lane_ids"] == [lane_id for _, lane_id in diag.PRIMARY_LANES]
    assert result["state"] == "WRITTEN"


@pytest.mark.parametrize("name,mutate", [
    ("perf02b-cell-family", lambda c: c.__setitem__("family", "retained-key")),
    ("perf02b-cell-regime", lambda c: c["workload"].__setitem__("regimes", ["process-cold"])),
    ("perf02b-cell-topk", lambda c: c["workload"].__setitem__("top_k", [10])),
    ("perf02b-cell-revisions", lambda c: c["arms"]["B"].__setitem__("revision", "d" * 40)),
    ("perf02b-cell-missing", lambda c: c["arms"]["A"].__setitem__("revision", None)),
    ("perf02b-cell-engine", lambda c: c["arms"]["B"].__setitem__("engine", "tantivy")),
])
def test_t02_rejects_invalid_identity_before_writing_requests(tmp_path, name, mutate):
    config_path = _mutated(tmp_path, mutate, name=name)
    out = tmp_path / "target" / "perf02b"
    with pytest.raises(artifacts.ArtifactError):
        diag.generate_inputs(config_path, out)
    assert not (out / "requests").exists()


def test_t02_rejects_configuration_outside_the_perf02_study_directory(tmp_path):
    config = configuration.default_configuration(
        "perf-02", "perf02b-misplaced", "Outside the canonical study root",
        timestamp="2026-11-22T10:00:00Z", regime="warm",
        baseline_revision=BASE, candidate_revision=BASE,
    )
    stray = artifacts.create_configuration(
        artifacts.configuration_directory(tmp_path / "studies", config), config)
    out = tmp_path / "target" / "perf02b"
    with pytest.raises(diag.DiagnosticError, match="benchmarks/studies/perf-02/warm/configurations"):
        diag.generate_inputs(stray, out)
    assert not (out / "requests").exists()


def test_t03_primary_profile_stream_shape_and_ordering(tmp_path):
    config_path, _config = _valid(tmp_path)
    out = tmp_path / "target" / "perf02b"
    diag.generate_inputs(config_path, out)
    expected = {
        "profile-n100000-medium-k10.jsonl": ("group", "medium", 10),
        "profile-n100000-medium-k100.jsonl": ("group", "medium", 100),
        "profile-n100000-common-k10.jsonl": ("key", "common", 10),
        "profile-n100000-common-k100.jsonl": ("key", "common", 100),
    }
    for name, (field, term, k) in expected.items():
        rows = diag._read_jsonl(out / "requests" / name)
        assert len(rows) == diag.PROFILE_WARMUPS + diag.PROFILE_SAMPLES == 900
        assert len({row["request_id"] for row in rows}) == 900
        for row in rows:
            assert (row["op"], row["field"], row["term"], row["k"], row["mode"]) == (
                "query", field, term, k, "warm")
        assert rows[0]["request_id"].endswith(":warmup:0")
        assert rows[diag.PROFILE_WARMUPS - 1]["request_id"].endswith(":warmup:99")
        assert rows[diag.PROFILE_WARMUPS]["request_id"].endswith(":sample:0")
        assert rows[-1]["request_id"].endswith(":sample:799")
        assert {row["request_id"].split(":")[0] for row in rows} == {"profile"}


def test_t04_baseline_stream_shape_and_warmup_then_sample_sequence(tmp_path):
    config_path, _config = _valid(tmp_path)
    out = tmp_path / "target" / "perf02b"
    diag.generate_inputs(config_path, out)
    for name, size in (("baseline-n10000.jsonl", 10_000),
                       ("baseline-n100000.jsonl", 100_000)):
        rows = diag._read_jsonl(out / "requests" / name)
        assert len(rows) == 8 * (diag.BASELINE_WARMUPS + diag.BASELINE_SAMPLES) == 480
        per_lane: dict[str, list[str]] = {}
        for row in rows:
            lane_id = row["request_id"].split(":")[1]
            per_lane.setdefault(lane_id, []).append(row["request_id"])
        assert len(per_lane) == 8
        expected_lanes = [lane["id"] for lane in configuration.lanes_for(_config)
                          if lane["n"] == size]
        assert list(per_lane) == expected_lanes
        for lane_id, identifiers in per_lane.items():
            kinds = [identifier.split(":")[2] for identifier in identifiers]
            indices = [int(identifier.split(":")[3]) for identifier in identifiers]
            assert kinds[:diag.BASELINE_WARMUPS] == ["warmup"] * diag.BASELINE_WARMUPS
            assert kinds[diag.BASELINE_WARMUPS:] == ["sample"] * diag.BASELINE_SAMPLES
            assert indices[:diag.BASELINE_WARMUPS] == list(range(diag.BASELINE_WARMUPS))
            assert indices[diag.BASELINE_WARMUPS:] == list(range(diag.BASELINE_SAMPLES))
            assert all(identifier.startswith(f"baseline:{lane_id}:") for identifier in identifiers)


# --------------------------------------------------------------------------- #
# T05 - T07: oracle-checked verification
# --------------------------------------------------------------------------- #


def test_t05_valid_replies_pass_oracle_and_exclude_warmups_from_statistics(tmp_path):
    config_path, config = _valid(tmp_path)
    out = tmp_path / "target" / "perf02b"
    diag.generate_inputs(config_path, out)
    request_file = out / "requests" / "profile-n100000-medium-k10.jsonl"
    rows = diag._read_jsonl(request_file)
    response_file = _write_responses(out, request_file.name, _replies(config, rows))
    output = out / "validated" / "profile-n100000-medium-k10.json"
    result = diag.verify_stream(config_path, request_file, response_file, output)
    assert result["state"] == "WRITTEN"
    record = json.loads(output.read_text())
    assert record["oracle_status"] == "PASS"
    assert record["warmups"] == diag.PROFILE_WARMUPS
    assert record["samples"] == diag.PROFILE_SAMPLES
    # Warmups used 500 ms, so a warmup leak into the statistics would dominate.
    assert record["median_engine_ms"] == 1.3995
    assert record["p90_engine_ms"] == 1.719
    assert record["median_engine_ns"] == 1_399_500
    assert record["p90_engine_ns"] == 1_719_000
    assert record["lane_id"] == "100000/medium/k10/warm"
    assert record["total_hits"] == 12_500
    assert record["mode"] == diag.DIAGNOSTIC_MODE
    assert record["timed_campaign"] is False
    assert set(record["checksums"]) == {"request_sha256", "response_sha256"}


def _corrupt(config: dict, rows: list[dict], mutation) -> list[dict]:
    replies = _replies(config, rows)
    mutation(replies)
    return replies


@pytest.mark.parametrize("mutation", [
    pytest.param(lambda rs: rs[719]["doc_ids"].reverse(), id="reordered-doc-ids"),
    pytest.param(lambda rs: rs[719].__setitem__("total_hits", 1), id="wrong-total-hits"),
    pytest.param(lambda rs: rs[719].__setitem__("request_id", "profile:stale"), id="stale-request-id"),
    pytest.param(lambda rs: rs.__setitem__(719, rs[718]), id="duplicate-response"),
])
def test_t06_rejects_oracle_and_identity_failures(tmp_path, mutation):
    config_path, config = _valid(tmp_path)
    out = tmp_path / "target" / "perf02b"
    diag.generate_inputs(config_path, out)
    request_file = out / "requests" / "profile-n100000-common-k100.jsonl"
    rows = diag._read_jsonl(request_file)
    response_file = _write_responses(out, request_file.name, _corrupt(config, rows, mutation))
    output = out / "validated" / "profile-n100000-common-k100.json"
    with pytest.raises(diag.DiagnosticError) as caught:
        diag.verify_stream(config_path, request_file, response_file, output)
    assert rows[719]["request_id"] in str(caught.value) or rows[718]["request_id"] in str(caught.value)
    assert not output.exists()


@pytest.mark.parametrize("mutation", [
    pytest.param(lambda rs, text: text.replace("\n", "", 1), id="json-parse-error"),
    pytest.param(lambda rs, text: text[: len(text) // 2], id="truncated-output"),
    pytest.param(lambda rs, text: text + _encode(rs[:1]), id="extra-response"),
    pytest.param(lambda rs, text: _encode(_with(rs, 5, {"engine": "tantivy"})), id="wrong-engine"),
    pytest.param(lambda rs, text: _encode(_with(rs, 5, {"schema": "other"})), id="wrong-schema"),
    pytest.param(lambda rs, text: _encode(_with(rs, 5, {"engine_ns": 0})), id="zero-engine-ns"),
    pytest.param(lambda rs, text: _encode(_with(rs, 5, {"engine_ns": True})), id="bool-engine-ns"),
])
def test_t07_rejects_malformed_replies_and_preserves_source_files(tmp_path, mutation):
    config_path, config = _valid(tmp_path)
    out = tmp_path / "target" / "perf02b"
    diag.generate_inputs(config_path, out)
    request_file = out / "requests" / "baseline-n10000.jsonl"
    rows = diag._read_jsonl(request_file)
    replies = _replies(config, rows)
    response_file = out / "responses" / request_file.name
    response_file.parent.mkdir(parents=True, exist_ok=True)
    response_file.write_text(mutation(replies, _encode(replies)), encoding="utf-8", newline="\n")
    request_before = request_file.read_bytes()
    response_before = response_file.read_bytes()
    output = out / "validated" / "baseline-n10000.json"
    with pytest.raises(diag.DiagnosticError):
        diag.verify_stream(config_path, request_file, response_file, output)
    assert not output.exists()
    assert request_file.read_bytes() == request_before
    assert response_file.read_bytes() == response_before


def _with(replies: list[dict], index: int, overrides: dict) -> list[dict]:
    copy = [dict(reply) for reply in replies]
    copy[index].update(overrides)
    return copy


# --------------------------------------------------------------------------- #
# T08 - T09: idempotence and attribution blocking
# --------------------------------------------------------------------------- #


def test_t08_regenerating_identical_inputs_is_a_safe_no_op(tmp_path):
    config_path, _config = _valid(tmp_path)
    out = tmp_path / "target" / "perf02b"
    first = diag.generate_inputs(config_path, out)
    snapshot = {path.name: path.read_bytes() for path in Path(first["directory"]).glob("*")}
    second = diag.generate_inputs(config_path, out)
    assert second["state"] == "REUSED"
    assert {path.name: path.read_bytes() for path in Path(second["directory"]).glob("*")} == snapshot

    tampered = Path(first["directory"]) / "profile-n100000-medium-k10.jsonl"
    tampered.write_text("{\"request_id\":\"x\"}\n", encoding="utf-8")
    with pytest.raises(diag.DiagnosticError, match="refusing to overwrite"):
        diag.generate_inputs(config_path, out)
    assert tampered.read_text(encoding="utf-8") == "{\"request_id\":\"x\"}\n"


def test_t09_missing_capture_fails_but_unrecognised_symbols_block_attribution(tmp_path):
    config_path, out, _config = _campaign(tmp_path)
    missing = out / "medium-k10.perf-report.txt"
    saved = missing.read_text(encoding="utf-8")
    missing.unlink()
    with pytest.raises(diag.DiagnosticError, match="perf report"):
        diag.summarize(config_path, out)
    missing.write_text(saved, encoding="utf-8")

    unsymbolised = _perf_record(["[unknown]"]) * 450
    for slug, _lane_id in diag.PRIMARY_LANES:
        (out / f"{slug}.perf-script.txt").write_text(unsymbolised, encoding="utf-8")
    result = diag.summarize(config_path, out)
    assert result["cpu_attribution_status"] == "CPU_ATTRIBUTION_BLOCKED"
    summary = json.loads((out / "summary.json").read_text())
    for profile in summary["profiles"]:
        assert profile["sort_query_cpu_share_percent"] is None
        assert profile["evidence_status"] == "INSUFFICIENT_VISIBILITY"
        assert profile["query_cpu_samples"] == 0


# --------------------------------------------------------------------------- #
# T10 - T11: nonoverlapping sample classification
# --------------------------------------------------------------------------- #


def test_t10_nested_sort_markers_are_counted_once_per_sample():
    nested = ["UnifiedSearcher::search", "UnifiedSearcher::collect_mixed",
              "consider_borrowed_keyword_candidate", "keyword_sort_view",
              "compare_borrowed_keyword_to_owned", "owned_keyword_sort_value",
              "materialize_keyword_entry", "admit_legacy_keyword_candidate",
              "sort_tuple_for_doc"]
    classification = diag.classify_perf_script(_perf_record(nested) * 420)
    assert classification["total_cpu_samples"] == 420
    assert classification["query_cpu_samples"] == 420
    assert classification["sort_cpu_samples"] == 420
    assert classification["other_query_samples"] == 0
    assert classification["sort_query_cpu_share_percent"] == 100.0
    assert classification["evidence_status"] == "PASS"


def test_t10_other_query_and_startup_samples_are_separate_buckets():
    query_only = _perf_record(["UnifiedSearcher::search", "evaluate_lexical_with"]) * 400
    startup = _perf_record(["std::rt::lang_start", "__libc_start_main"]) * 40
    classification = diag.classify_perf_script(query_only + startup)
    assert classification["query_cpu_samples"] == 400
    assert classification["sort_cpu_samples"] == 0
    assert classification["other_query_samples"] == 400
    assert classification["startup_overhead_samples"] == 40
    assert classification["unknown_samples"] == 0
    assert classification["sort_query_cpu_share_percent"] == 0.0
    assert classification["evidence_status"] == "PASS"


def test_t11_absent_search_frame_or_unsymbolised_denominator_blocks_attribution():
    startup_only = diag.classify_perf_script(
        _perf_record(["std::rt::lang_start", "__libc_start_main"]) * 500)
    assert startup_only["query_cpu_samples"] == 0
    assert startup_only["evidence_status"] == "INSUFFICIENT_VISIBILITY"
    assert startup_only["sort_query_cpu_share_percent"] is None

    unsymbolised = diag.classify_perf_script(_perf_record(["[unknown]"]) * 500)
    assert unsymbolised["unknown_samples"] == 500
    assert unsymbolised["evidence_status"] == "INSUFFICIENT_VISIBILITY"
    assert unsymbolised["sort_query_cpu_share_percent"] is None

    too_few = diag.classify_perf_script(
        _perf_record(["UnifiedSearcher::search", "consider_borrowed_keyword_candidate"]) * 399)
    assert too_few["query_cpu_samples"] == 399
    assert too_few["evidence_status"] == "INSUFFICIENT_VISIBILITY"


def test_t11_foreign_process_samples_are_unknown_never_a_small_hotspot():
    foreign = _perf_record(["UnifiedSearcher::search", "keyword_sort_view"],
                           comm="pr15d-tantivy") * 600
    classification = diag.classify_perf_script(foreign)
    assert classification["query_cpu_samples"] == 0
    assert classification["other_process_samples"] == 600
    assert classification["unknown_samples"] == 600
    assert classification["evidence_status"] == "INSUFFICIENT_VISIBILITY"


def test_summary_is_deterministic_and_never_a_benchmark_result(tmp_path):
    config_path, out, _config = _campaign(tmp_path)
    first = diag.summarize(config_path, out)
    payload = (out / "summary.json").read_bytes()
    second = diag.summarize(config_path, out)
    assert first["state"] == "WRITTEN"
    assert second["state"] == "REUSED"
    summary = json.loads(payload)
    assert summary["benchmark_result_v1"] is False
    assert summary["timed_campaign"] is False
    assert summary["mode"] == diag.DIAGNOSTIC_MODE
    assert len(summary["baseline"]) == 16
    assert len(summary["profiles"]) == 4
    assert summary["cpu_attribution_status"] == "PASS"
    assert [profile["profile_slug"] for profile in summary["profiles"]] == [
        slug for slug, _ in diag.PRIMARY_LANES]
    assert (out / "summary.json").read_bytes() == payload


# --------------------------------------------------------------------------- #
# T12: no process, profiler or benchmark execution
# --------------------------------------------------------------------------- #


def test_t12_helpers_never_spawn_processes_or_run_benchmarks(tmp_path, monkeypatch):
    assert not hasattr(diag, "subprocess")

    def explode(*_args, **_kwargs):
        raise AssertionError("PERF-02-B helpers must not spawn a subprocess")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)
    config_path, out, _config = _campaign(tmp_path)
    result = diag.summarize(config_path, out)
    assert result["cpu_attribution_status"] == "PASS"


def test_cli_rejects_unknown_arguments_and_reports_errors(tmp_path, capsys):
    with pytest.raises(SystemExit):
        diag.main(["inputs", "--config", str(tmp_path / "missing.json")])
    assert "error:" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        diag.main(["nonsense"])


def test_nearest_rank_p90_is_not_interpolated():
    assert diag.nearest_rank_p90([5]) == 5
    assert diag.nearest_rank_p90(list(range(1, 11))) == 9
    assert diag.nearest_rank_p90([10, 1, 9, 2, 8]) == 10
    with pytest.raises(diag.DiagnosticError):
        diag.nearest_rank_p90([])


# --------------------------------------------------------------------------- #
# Fail-closed identity, protocol and evidence-shape behaviours
# --------------------------------------------------------------------------- #


def _arm_config() -> dict:
    return configuration.default_configuration(
        "perf-02", "perf02b-arm-rules", "Arm-rule fixture",
        timestamp="2026-11-22T10:00:00Z", regime="warm",
        baseline_revision=BASE, candidate_revision=BASE,
    )


@pytest.mark.parametrize("mutate", [
    lambda c: c.__setitem__("family", "cross-engine"),
    lambda c: c.__setitem__("baseline", "B"),
    lambda c: c["workload"].__setitem__("regimes", ["process-cold"]),
    lambda c: c.__setitem__("arms", {"A": c["arms"]["A"]}),
    lambda c: c["arms"].__setitem__("A", "not-an-object"),
    lambda c: c["arms"]["A"].__setitem__("engine", "tantivy"),
    lambda c: c["arms"]["A"].__setitem__("mode", "prefilter"),
    lambda c: c["arms"]["A"].__setitem__("source", "current"),
    lambda c: c["arms"]["A"].__setitem__("revision", "f" * 39),
    lambda c: c["arms"]["A"].__setitem__("revision", BASE.upper()),
    lambda c: c["arms"]["B"].__setitem__("revision", "d" * 40),
])
def test_t02_arm_rules_are_fail_closed_without_a_benchmark_run(mutate):
    config = _arm_config()
    assert diag._require_pinned_a_equal_a(config) == BASE
    mutate(config)
    with pytest.raises(diag.DiagnosticError):
        diag._require_pinned_a_equal_a(config)


def _profile_request_rows(tmp_path):
    config_path, config = _valid(tmp_path)
    out = tmp_path / "target" / "perf02b"
    diag.generate_inputs(config_path, out)
    request_file = out / "requests" / "profile-n100000-medium-k10.jsonl"
    rows = diag._read_jsonl(request_file)
    return config_path, config, out, request_file, rows


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda rows: rows[0].__setitem__("op", "build"), id="index-build-op"),
    pytest.param(lambda rows: rows[0].__setitem__("mode", "process-cold"), id="cold-mode"),
    pytest.param(lambda rows: rows[0].__setitem__("field", "key"), id="wrong-field"),
    pytest.param(lambda rows: rows[0].__setitem__("term", "other"), id="wrong-term"),
    pytest.param(lambda rows: rows[0].__setitem__("k", 100), id="wrong-k"),
    pytest.param(lambda rows: rows[0].__setitem__("request_id", "garbage"), id="bad-request-id"),
    pytest.param(lambda rows: rows[0].__setitem__(
        "request_id", "profile:999999/rare/k10/warm:warmup:0"), id="unknown-lane"),
    pytest.param(lambda rows: rows[0].__setitem__(
        "request_id", "profile:100000/medium/k10/warm:warmup:x"), id="bad-index"),
    pytest.param(lambda rows: rows[0].pop("request_id"), id="missing-request-id"),
    pytest.param(lambda rows: rows.__setitem__(0, rows[1]), id="duplicated-request"),
    pytest.param(lambda rows: rows.pop(), id="short-request-stream"),
    pytest.param(lambda rows: rows.__setitem__(
        0, {**rows[0], "request_id": "baseline:100000/medium/k10/warm:warmup:0"}),
        id="mixed-phase"),
])
def test_request_stream_violations_are_rejected_before_any_summary(tmp_path, mutate):
    config_path, config, out, request_file, rows = _profile_request_rows(tmp_path)
    responses = _replies(config, rows)
    mutated = [dict(row) for row in rows]
    mutate(mutated)
    mutated_file = out / "mutated-requests" / request_file.name
    mutated_file.parent.mkdir(parents=True, exist_ok=True)
    mutated_file.write_text(_encode(mutated), encoding="utf-8", newline="\n")
    response_file = _write_responses(out, request_file.name, responses)
    output = out / "validated" / "mutated.json"
    with pytest.raises(diag.DiagnosticError):
        diag.verify_stream(config_path, mutated_file, response_file, output)
    assert not output.exists()


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda rs: rs[0].__setitem__("status", "error"), id="error-status"),
    pytest.param(lambda rs: rs[0].__setitem__("total_hits", "12500"), id="string-total-hits"),
    pytest.param(lambda rs: rs[0].__setitem__("total_hits", True), id="bool-total-hits"),
    pytest.param(lambda rs: rs[0].__setitem__("total_hits", -1), id="negative-total-hits"),
    pytest.param(lambda rs: rs[0].__setitem__("engine", "tantivy"), id="wrong-engine"),
])
def test_reply_status_and_count_violations_are_rejected(tmp_path, mutate):
    config_path, config, out, request_file, rows = _profile_request_rows(tmp_path)
    responses = _replies(config, rows)
    mutate(responses)
    response_file = _write_responses(out, request_file.name, responses)
    with pytest.raises(diag.DiagnosticError):
        diag.verify_stream(config_path, request_file, response_file,
                           out / "validated" / "rejected.json")


def test_incomplete_reply_stream_names_the_first_missing_request_id(tmp_path):
    config_path, config, out, request_file, rows = _profile_request_rows(tmp_path)
    responses = _replies(config, rows)[:-1]
    response_file = _write_responses(out, request_file.name, responses)
    with pytest.raises(diag.DiagnosticError) as caught:
        diag.verify_stream(config_path, request_file, response_file,
                           out / "validated" / "short.json")
    assert rows[-1]["request_id"] in str(caught.value)


def test_jsonl_reader_rejects_unusable_streams(tmp_path):
    good = tmp_path / "rows.jsonl"
    good.write_text('{"a":1}\n', encoding="utf-8")
    assert diag._read_jsonl(good) == [{"a": 1}]

    duplicated = tmp_path / "duplicate.jsonl"
    duplicated.write_text('{"a":1,"a":2}\n', encoding="utf-8")
    with pytest.raises(diag.DiagnosticError):
        diag._read_jsonl(duplicated)

    binary = tmp_path / "binary.jsonl"
    binary.write_bytes(b"\xff\xfe\n")
    with pytest.raises(diag.DiagnosticError):
        diag._read_jsonl(binary)

    crlf = tmp_path / "crlf.jsonl"
    crlf.write_bytes(b'{"a":1}\r\n')
    with pytest.raises(diag.DiagnosticError):
        diag._read_jsonl(crlf)

    empty_line = tmp_path / "empty.jsonl"
    empty_line.write_text('{"a":1}\n\n{"a":2}\n', encoding="utf-8")
    with pytest.raises(diag.DiagnosticError):
        diag._read_jsonl(empty_line)

    not_object = tmp_path / "list.jsonl"
    not_object.write_text("[1]\n", encoding="utf-8")
    with pytest.raises(diag.DiagnosticError):
        diag._read_jsonl(not_object)

    link = tmp_path / "link.jsonl"
    link.symlink_to(good)
    with pytest.raises(diag.DiagnosticError):
        diag._read_jsonl(link)


def test_perf_script_layout_and_event_edge_cases():
    # A non cpu-clock event is ignored entirely.
    other_event = _perf_record(["UnifiedSearcher::search"], event="task-clock")
    assert diag.classify_perf_script(other_event)["total_cpu_samples"] == 0
    assert diag.classify_perf_script(other_event)["evidence_status"] == "INSUFFICIENT_VISIBILITY"

    # A header-only (no call graph) sample still classifies from its inline symbol.
    inline = "pr15d-quervant  1/1  12.5: cpu-clock:u: 0000000000001000 UnifiedSearcher::search (/x/adapter)\n\n"
    parsed = diag.classify_perf_script(inline)
    assert parsed["total_cpu_samples"] == 1
    assert parsed["query_cpu_samples"] == 1

    with pytest.raises(diag.DiagnosticError, match="before any event header"):
        diag.classify_perf_script("\t    0000000000001000 symbol (/x)\n")
    with pytest.raises(diag.DiagnosticError, match="event header"):
        diag.classify_perf_script("not a perf header\n\n")
    with pytest.raises(diag.DiagnosticError, match="callchain frame"):
        diag.classify_perf_script(
            "pr15d-quervant  1/1  12.5: cpu-clock:u: \n\t    not-a-frame\n\n")


@pytest.mark.parametrize("mutate", [
    lambda data: data[0].__setitem__("source_revision", "0" * 40),
    lambda data: data[0].__setitem__("configuration_id", "00000000-0000-4000-8000-000000000000"),
    lambda data: data[0].__setitem__("mode", "timed"),
    lambda data: data[0].__setitem__("benchmark_result_v1", True),
    lambda data: data[0].__setitem__("timed_campaign", True),
    lambda data: data.pop(),
    lambda data: data[1].__setitem__("lane_id", data[0]["lane_id"]),
])
def test_summarize_rejects_mismatched_validated_evidence(tmp_path, mutate):
    config_path, out, _config = _campaign(tmp_path)
    path = out / "validated" / "baseline-n10000.json"
    data = json.loads(path.read_text())
    mutate(data)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(diag.DiagnosticError):
        diag.summarize(config_path, out)


@pytest.mark.parametrize("mutate,message", [
    (lambda record: record.__setitem__("lane_id", "100000/common/k100/warm"), "declares lane"),
    (lambda record: record.__setitem__("samples", 799), "100\\+800"),
    (lambda record: record.__setitem__("warmups", 5), "100\\+800"),
    (lambda record: record.__setitem__("mode", "timed"), "diagnostic-unqualified"),
])
def test_summarize_rejects_mismatched_profile_metadata(tmp_path, mutate, message):
    config_path, out, _config = _campaign(tmp_path)
    path = out / "validated" / "profile-n100000-medium-k10.json"
    record = json.loads(path.read_text())
    mutate(record)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(diag.DiagnosticError, match=message):
        diag.summarize(config_path, out)


def test_summarize_rejects_unreadable_perf_captures_and_never_lies(tmp_path):
    config_path, out, _config = _campaign(tmp_path)
    (out / "medium-k10.perf-report.txt").write_text("   \n", encoding="utf-8")
    with pytest.raises(diag.DiagnosticError, match="empty"):
        diag.summarize(config_path, out)

    (out / "medium-k10.perf-report.txt").write_text("# context\n", encoding="utf-8")
    (out / "medium-k10.perf-script.txt").write_bytes(b"\xff\xfe")
    with pytest.raises(diag.DiagnosticError, match="cannot read"):
        diag.summarize(config_path, out)


def test_summarize_refuses_to_overwrite_different_evidence(tmp_path):
    config_path, out, _config = _campaign(tmp_path)
    diag.summarize(config_path, out)
    summary = out / "summary.json"
    summary.write_text("{}\n", encoding="utf-8")
    with pytest.raises(diag.DiagnosticError, match="refusing to overwrite"):
        diag.summarize(config_path, out)
    assert summary.read_text(encoding="utf-8") == "{}\n"


def test_write_once_and_load_refuse_unsafe_destinations(tmp_path):
    real = tmp_path / "real.txt"
    real.write_bytes(b"payload")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    with pytest.raises(diag.DiagnosticError, match="symlink"):
        diag._write_once(link, b"payload")
    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(diag.DiagnosticError, match="not a regular file"):
        diag._write_once(directory, b"payload")

    config_path, _config = _valid(tmp_path)
    config_link = tmp_path / "config-link.json"
    config_link.symlink_to(config_path)
    with pytest.raises(diag.DiagnosticError, match="symlink"):
        diag._load(config_link)


def test_cli_success_paths_print_json_and_return_zero(tmp_path, capsys):
    config_path, out, _config = _campaign(tmp_path)
    assert diag.main(["inputs", "--config", str(config_path), "--output-dir", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "REUSED"

    request_file = out / "requests" / "baseline-n10000.jsonl"
    response_file = out / "responses" / request_file.name
    output = out / "validated" / "rechecked-baseline-n10000.json"
    assert diag.main(["verify", "--config", str(config_path),
                      "--request-file", str(request_file),
                      "--response-file", str(response_file),
                      "--output", str(output)]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["phase"] == "baseline" and len(body["lanes"]) == 8

    assert diag.main(["summarize", "--config", str(config_path),
                      "--output-dir", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["cpu_attribution_status"] == "PASS"


# --------------------------------------------------------------------------- #
# PERF-02-B offline Rust-v0 symbol-attribution fixup (FX01 - FX05)
# --------------------------------------------------------------------------- #

_RUST_V0_ROOT = "<quervant_core[b08e6442fe3ff266]::search::unified::UnifiedSearcher>::search"
_RUST_V0_BORROWED = (
    "quervant_core[b08e6442fe3ff266]::search::unified::consider_borrowed_keyword_candidate"
)
_RUST_V0_SORT_VIEW = "quervant_core[b08e6442fe3ff266]::segment::column::keyword_sort_view"
_RUST_V0_EVALUATE = (
    "quervant_core[abcdef1234567890]::search::execute::evaluate_lexical_with"
)


def test_fx01_rust_v0_crate_hash_and_qualified_method_forms_are_recognised():
    stack = [_RUST_V0_ROOT, _RUST_V0_BORROWED, _RUST_V0_SORT_VIEW]
    classification = diag.classify_perf_script(_perf_record(stack) * 420)
    assert classification["total_cpu_samples"] == 420
    assert classification["query_cpu_samples"] == 420
    assert classification["sort_cpu_samples"] == 420
    assert classification["other_query_samples"] == 0
    assert classification["root_chain_visible"] is True
    assert classification["sort_query_cpu_share_percent"] == 100.0
    assert classification["evidence_status"] == "PASS"


def test_fx02_rust_v0_query_stack_without_sort_markers_is_other_query():
    stack = [_RUST_V0_ROOT, _RUST_V0_EVALUATE]
    classification = diag.classify_perf_script(_perf_record(stack) * 420)
    assert classification["query_cpu_samples"] == 420
    assert classification["sort_cpu_samples"] == 0
    assert classification["other_query_samples"] == 420
    assert classification["root_chain_visible"] is True
    assert classification["sort_query_cpu_share_percent"] == 0.0
    assert classification["evidence_status"] == "PASS"


def test_fx03_existing_unhashed_symbols_keep_their_previous_classification():
    hashed = diag.classify_perf_script(_perf_record([_RUST_V0_ROOT, _RUST_V0_BORROWED]) * 420)
    plain = diag.classify_perf_script(
        _perf_record(["UnifiedSearcher::search",
                      "quervant_core::search::unified::consider_borrowed_keyword_candidate"]) * 420)
    assert plain == hashed
    assert plain["query_cpu_samples"] == 420
    assert plain["sort_cpu_samples"] == 420
    assert plain["root_chain_visible"] is True


def test_fx04_mangled_or_unrecognised_stacks_do_not_infer_a_zero_sort_share():
    mangled = _perf_record([
        "_RNvMs1_NtNtCsf9NSTe8eULi_13quervant_core6search7unifiedNtB5_15UnifiedSearcher6search",
        "_RNvMs1_NtNtCsf9NSTe8eULi_13quervant_core6search7unifiedNtB5_15UnifiedSearcher15execute_unified",
    ]) * 420
    classification = diag.classify_perf_script(mangled)
    assert classification["query_cpu_samples"] == 0
    assert classification["sort_cpu_samples"] == 0
    assert classification["root_chain_visible"] is False
    assert classification["evidence_status"] == "INSUFFICIENT_VISIBILITY"
    assert classification["sort_query_cpu_share_percent"] is None


def test_fx05_foreign_process_and_unrelated_crate_are_never_eligible():
    foreign = diag.classify_perf_script(
        _perf_record([_RUST_V0_ROOT, _RUST_V0_BORROWED], comm="pr15d-tantivy") * 420)
    assert foreign["query_cpu_samples"] == 0
    assert foreign["root_chain_visible"] is False
    assert foreign["other_process_samples"] == 420
    assert foreign["evidence_status"] == "INSUFFICIENT_VISIBILITY"

    unrelated = diag.classify_perf_script(
        _perf_record(["other_crate[0123456789abcdef]::search::OtherSearcher::search",
                      "other_crate[0123456789abcdef]::search::OtherSearcher::collect_mixed"]) * 420)
    assert unrelated["query_cpu_samples"] == 0
    assert unrelated["sort_cpu_samples"] == 0
    assert unrelated["root_chain_visible"] is False
    assert unrelated["unknown_samples"] == 420
    assert unrelated["evidence_status"] == "INSUFFICIENT_VISIBILITY"


def test_fx_canonicalisation_is_narrow_and_does_not_touch_other_crates():
    assert diag._canonical_perf_symbol(_RUST_V0_ROOT).endswith("UnifiedSearcher::search")
    assert diag._canonical_perf_symbol(_RUST_V0_SORT_VIEW) == (
        "quervant_core::segment::column::keyword_sort_view")
    assert diag._canonical_perf_symbol("other_crate[b08e6442fe3ff266]::search::Thing") == (
        "other_crate[b08e6442fe3ff266]::search::Thing")
    assert diag._canonical_perf_symbol("UnifiedSearcher::search") == "UnifiedSearcher::search"
    assert diag._canonical_perf_symbol("malloc") == "malloc"
