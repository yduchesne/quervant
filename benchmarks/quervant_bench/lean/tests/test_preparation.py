"""Deterministic prepared-input cache and phase-timing contract tests.

All compilers, adapters and index builders are mocked; NO real benchmark.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from quervant_bench.lean import artifacts, cli, configuration, preparation, reporting, runtime, statistics


def _config(tmp_path, family="cross-engine", regime="warm"):
    cfg = configuration.default_configuration(
        family, "stage-test-" + regime,
        "Deterministic preparation cache test",
        timestamp="2026-11-22T10:00:00Z", regime=regime,
    )
    cfg["policy"].update(blocks=6 if family=="cross-engine" else 12,
                         samples=3, bootstrap_resamples=100)
    path = artifacts.create_configuration(
        artifacts.configuration_directory(tmp_path / "studies", cfg), cfg)
    return path, cfg


def _mocks(monkeypatch):
    calls: list[tuple[str, str]] = []
    source = {"revision": "abc", "env": "stable", "toolchain": "rust-1.98"}
    monkeypatch.setattr(preparation, "source_identity",
                        lambda root, config: {**source,
                                              "configuration_hash": preparation._digest(config)})
    def build(config, root, dest):
        calls.append(("build", config["name"]))
        out = {}
        for arm, spec in config["arms"].items():
            eng = spec["engine"]
            if eng == "lucene":
                binary = (dest / "build" / "lucene" / "install"
                          / "pr15d-lucene-adapter" / "bin" / "pr15d-lucene-adapter")
                lib = binary.parent.parent / "lib" / "lucene.jar"
                lib.parent.mkdir(parents=True, exist_ok=True)
                lib.write_text("lucene-jar")
            else:
                role = "baseline" if arm == "A" and config["family"] == "retained-key" else eng
                binary = dest / "build" / role / "release" / f"pr15d-{eng}-adapter"
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_bytes(f"executable:{eng}:{arm}".encode())
            out[arm] = [str(binary)]
        return out, {"compiler_options":"MOCKED", "source_revision":"abc"}
    def corpus(path, n):
        calls.append(("corpus", str(n)))
        path.write_text(f"synthetic-corpus:{n}")
    def index(command, *, engine, corpus_path, target, n, cpu):
        calls.append(("index", f"{engine}:{n}"))
        target.mkdir(parents=True, exist_ok=False)
        (target / "segments.dat").write_text(f"index:{engine}:{n}")
        return {"index_ns":3, "commit_ns":4, "reopen_ns":5, "index_bytes":6,
                "segment_count":1}
    def oracle(config, commands, indexes, cpu):
        calls.append(("oracle", config["name"]))
        assert set(indexes) == set(config["arms"])
        for arm in indexes:
            for n in config["workload"]["sizes"]:
                assert (indexes[arm][n] / "segments.dat").is_file()
    monkeypatch.setattr(runtime, "build_programs", build)
    monkeypatch.setattr(runtime, "create_corpus", corpus)
    monkeypatch.setattr(runtime, "build_index", index)
    monkeypatch.setattr(preparation, "_verify_oracles", oracle)
    return source, calls


def test_stage_first_build_then_hit_no_recompilation_or_indexing(tmp_path, monkeypatch):
    path, cfg = _config(tmp_path)
    source, calls = _mocks(monkeypatch)
    first = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    assert first["state"] == "BUILT"
    assert len([x for x in calls if x[0] == "build"]) == 1
    assert len([x for x in calls if x[0] == "index"]) == 6
    assert first["phase_durations_ns"]["build_ns"] > 0
    assert first["phase_durations_ns"]["index_ns"] > 0
    assert first["phase_durations_ns"]["oracle_ns"] > 0
    second = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    assert second["state"] == "HIT"
    assert first["key"] == second["key"]
    assert first["index_metrics"] == second["index_metrics"]
    assert first["prepared_utc"] == second["prepared_utc"]
    assert len([x for x in calls if x[0] == "build"]) == 1
    assert len([x for x in calls if x[0] == "index"]) == 6
    assert len([x for x in calls if x[0] == "oracle"]) == 2
    assert "build_ns" not in second["phase_durations_ns"]
    assert "index_ns" not in second["phase_durations_ns"]
    assert Path(first["cache_dir"], "prepared.json").is_file()
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("tamper", ["index", "corpus", "binary", "manifest", "symlink"])
def test_published_cache_corruption_fails_closed_without_destroying_inputs(
        tmp_path, monkeypatch, tamper):
    path, _cfg = _config(tmp_path)
    source, calls = _mocks(monkeypatch)
    prepared = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    cache = Path(prepared["cache_dir"])
    binary = Path(prepared["programs"]["Q"][0])
    if tamper == "index":
        (cache / "indexes" / "Q" / "n10000" / "segments.dat").write_text("changed")
    elif tamper == "corpus":
        (cache / "corpus" / "keyword-n10000.tsv").write_text("changed")
    elif tamper == "binary":
        binary.write_bytes(b"changed binary")
    elif tamper == "manifest":
        (cache / "prepared.json").write_text('{"schema":"invalid"}')
    else:
        part = cache / "indexes" / "Q" / "n10000" / "segments.dat"
        part.unlink()
        part.symlink_to("/etc/passwd")
    with pytest.raises(runtime.MeasurementBlocked, match="cache failed validation"):
        preparation.stage_inputs(path, root=tmp_path, check_host=False)
    assert cache.exists()
    assert len([x for x in calls if x[0] == "build"]) == 1
    assert len([x for x in calls if x[0] == "oracle"]) == 1


def test_interrupted_partial_preparation_is_rebuilt(tmp_path, monkeypatch):
    path, cfg = _config(tmp_path)
    _source, calls = _mocks(monkeypatch)
    first = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    cache = Path(first["cache_dir"])
    (cache / "prepared.json").unlink()
    second = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    assert second["state"] == "BUILT"
    assert second["key"] == first["key"]
    assert len([x for x in calls if x[0] == "build"]) == 2


def test_source_environment_or_config_change_forces_new_preparation(tmp_path,monkeypatch):
    path, cfg = _config(tmp_path)
    source, calls = _mocks(monkeypatch)
    first = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    source["revision"] = "changed-source"
    second = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    assert second["key"] != first["key"] and second["state"] == "BUILT"
    source["env"] = "new-build-flags"
    third = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    assert third["key"] not in (first["key"], second["key"])
    assert len([x for x in calls if x[0] == "build"]) == 3


def test_separately_staged_cold_study_does_not_share_warm_inputs(tmp_path, monkeypatch):
    warm, _ = _config(tmp_path, regime="warm")
    cold, _ = _config(tmp_path, regime="process-cold")
    _source,calls = _mocks(monkeypatch)
    a = preparation.stage_inputs(warm, root=tmp_path, check_host=False)
    b = preparation.stage_inputs(cold, root=tmp_path, check_host=False)
    assert a["key"] != b["key"]
    assert a["index_metrics"]["Q"].keys() == {"10000","100000"}
    assert b["index_metrics"]["Q"].keys() == {"10000"}
    assert len([x for x in calls if x[0] == "index"]) == 9


def test_concurrent_staging_acquires_one_lock_and_builds_once(tmp_path, monkeypatch):
    path, cfg = _config(tmp_path)
    _source,calls = _mocks(monkeypatch)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(
            lambda _: preparation.stage_inputs(path,root=tmp_path,check_host=False),range(3)))
    assert sorted(x["state"] for x in results) == ["BUILT","HIT","HIT"]
    assert len([x for x in calls if x[0] == "build"]) == 1


def test_oracle_validation_rejects_bad_index_without_benchmark_samples(tmp_path, monkeypatch):
    cfg=configuration.default_configuration("cross-engine","oracle-test","Oracle smoke")
    commands={"Q":["/fake/quervant"],"T":["/fake/tantivy"],"J":["/fake/lucene"]}
    indexes={arm:{n:tmp_path / arm / str(n) for n in cfg["workload"]["sizes"]}
             for arm in cfg["arms"]}
    received=[]
    def fake_process(argv,cpu,*,env,input_text,timeout):
        from subprocess import CompletedProcess
        engine=Path(argv[0]).name
        n=int(Path(argv[-1]).name)
        requests=[json.loads(row) for row in input_text.splitlines()]
        received.append((engine,n,len(requests)))
        rows=[]
        for r in requests:
            count, docs=runtime.expected_answer(n,r["field"],r["term"],r["k"])
            rows.append({"schema":runtime.ADAPTER_SCHEMA,"engine":engine,
                         "request_id":r["request_id"],"status":"ok",
                         "total_hits":count,"doc_ids":docs,"engine_ns":100})
        return CompletedProcess(argv,0,"".join(json.dumps(x)+"\n" for x in rows),"")
    monkeypatch.setattr(runtime,"_run_pinned",fake_process)
    preparation._verify_oracles(cfg,commands,indexes,cpu=None)
    assert len(received)==6
    assert sum(x[2] for x in received)==len(configuration.lanes_for(cfg))*3


def test_clean_source_allows_untracked_result_but_blocks_dirty_code(monkeypatch,tmp_path):
    sha="a"*40
    dirty={"text":"?? benchmarks/studies/cross-engine/warm/results/warm-2026-11-22-001.json"}
    def git(root,*args):
        return sha if args==("rev-parse","HEAD") else dirty["text"]
    monkeypatch.setattr(runtime,"_git",git)
    assert preparation._clean_source(tmp_path)==sha
    dirty["text"]=" M benchmarks/quervant_bench/lean/runtime.py"
    with pytest.raises(runtime.MeasurementBlocked, match="committed clean source"):
        preparation._clean_source(tmp_path)


def test_run_reuses_stage_and_records_timing_phases(tmp_path, monkeypatch):
    path, cfg = _config(tmp_path)
    source, calls = _mocks(monkeypatch)
    monkeypatch.setattr(runtime,"host_context",lambda path,check: {
        "physical_core_candidates":[], "filesystem":"MOCKED"})
    monkeypatch.setattr(runtime,"_git",lambda root,*args:"a"*40)
    # This lane is also the mandatory serial-throughput reference.
    lane = next(ln for ln in configuration.lanes_for(cfg)
                if ln["id"] == "10000/medium/k10/warm")
    monkeypatch.setattr(runtime,"lanes_for",lambda config:[lane])
    def phase(config,lanes,binaries,indexes,*,cpu,on_slot):
        values={"AA":100,"AA2":100,"Q":100,"T":120,"J":130}
        slot_rows=statistics.schedule(list(config["arms"]),blocks=config["policy"]["blocks"],
                     slots_per_arm=config["policy"]["slots_per_arm"],seed=config["policy"]["seed"])
        rows=[{"arm_id":p["arm_id"],"block":p["block"],"position":p["position"],
               "lane_id":lane["id"],"oracle_ok":True,
               "samples_ns":[values[p["arm_id"]]]*config["policy"]["samples"]}
              for p in slot_rows]
        on_slot(rows)
        return rows
    monkeypatch.setattr(runtime,"_phase",phase)
    monkeypatch.setattr(runtime,"collect_throughput",
        lambda command,*,engine,index_dir,lane,config,arm_id,cpu,requests=100:
        {"status":"MEASURED","lane_id":lane["id"],"serial_ops_per_second":1.0,
         "requests":100,"warmups":5,"wall_ns":100})
    first_path, first = runtime.run_benchmark(path,root=tmp_path,check_host=False)
    second_path, second = runtime.run_benchmark(path,root=tmp_path,check_host=False)
    assert first["status"] == second["status"] == "COMPLETE"
    assert first["context"]["preparation"]["cache_status"] == "BUILT"
    assert second["context"]["preparation"]["cache_status"] == "HIT"
    assert first["index_metrics"] == second["index_metrics"]
    assert first["context"]["preparation"]["prepared_utc"] == second["context"]["preparation"]["prepared_utc"]
    assert len([x for x in calls if x[0]=="build"]) == 1
    assert len([x for x in calls if x[0]=="index"]) == 6
    assert "preparation_build_ns" in first["phase_durations_ns"]
    assert "preparation_index_ns" in first["phase_durations_ns"]
    assert "preparation_build_ns" not in second["phase_durations_ns"]
    for name in ("aa_acquisition_ns","treatment_acquisition_ns","throughput_acquisition_ns",
                 "preparation_ns","run_before_save_ns"):
        assert second["phase_durations_ns"][name] > 0
    rendered=reporting.replay_to_markdown(second_path)
    assert "Phase durations" in rendered
    assert "HIT" in rendered
    assert artifacts.load_result(second_path)["sequence"] == 2
    assert artifacts.load_result(first_path)["sequence"] == 1

def test_cli_stage_builds_inputs_only_without_benchmark_result(tmp_path,monkeypatch,capsys):
    path,cfg = _config(tmp_path)
    _source,calls = _mocks(monkeypatch)
    monkeypatch.setattr(cli,"repo_root",lambda:tmp_path)
    monkeypatch.setattr(preparation,"stage_inputs",
                        lambda path,*,root,scratch_root=None,check_host=True,cpu=None: {
                            "state":"HIT","key":"fixture-key",
                            "prepared_utc":"2026-11-22T10:00:00Z",
                            "phase_durations_ns":{"lookup_ns":100},
                        })
    monkeypatch.setattr(cli,"run_benchmark",
                        lambda *a,**k:(_ for _ in ()).throw(
                            AssertionError("stage must not execute timed benchmark")))
    assert cli.main(["stage","--config",str(path)])==0
    out=capsys.readouterr().out
    assert "PREPARATION=HIT" in out
    assert "PREPARATION_KEY=fixture-key" in out
    assert "PHASE_DURATIONS_NS=" in out
    assert not list((path.parent.parent / "results").glob("*.json"))

def test_retained_key_stages_historical_baseline_and_reuses_three_shared_modes(
        tmp_path, monkeypatch):
    path, cfg = _config(tmp_path, family="retained-key")
    _source, calls = _mocks(monkeypatch)
    first = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    second = preparation.stage_inputs(path, root=tmp_path, check_host=False)
    assert first["state"] == "BUILT" and second["state"] == "HIT"
    assert "/build/baseline/release/" in first["programs"]["A"][0]
    assert first["programs"]["L"] == first["programs"]["P"] == first["programs"]["H"]
    assert len([x for x in calls if x[0] == "build"]) == 1
    assert len([x for x in calls if x[0] == "index"]) == 8


def test_retained_key_does_not_require_java_and_cross_engine_does(tmp_path, monkeypatch):
    monkeypatch.setattr(preparation, "_clean_source", lambda root: "a" * 40)
    monkeypatch.setattr(runtime, "_git",
                        lambda root,*args: "100644 blob " + ("b" * 40) + "\t" + args[-1])
    monkeypatch.setattr(runtime, "_tool",
                        lambda argv: "UNAVAILABLE" if argv[0] == "java" else "mock-version")
    retained = configuration.default_configuration("retained-key", "rust-only", "Rust toolchain")
    identity = preparation.source_identity(tmp_path, retained)
    assert identity["toolchains"]["java"] == "NOT_REQUIRED"
    cross = configuration.default_configuration("cross-engine", "needs-java", "Lucene included")
    with pytest.raises(runtime.MeasurementBlocked, match="toolchain identity unavailable"):
        preparation.source_identity(tmp_path, cross)


def test_prep_source_tree_identity_ignores_results_only_head_change(tmp_path,monkeypatch):
    state={"sha":"a"*40, "crate_object":"c"*40}
    def fake_git(root,*args):
        if args==("rev-parse","HEAD"):
            return state["sha"]
        if args[:2]==("status","--porcelain=v1"):
            return "?? benchmarks/studies/cross-engine/warm/results/run-2026-11-22-001.json"
        if args[:3]==("ls-tree","HEAD","--"):
            path=args[3]
            obj=state["crate_object"] if path=="crates" else "d"*40
            return "040000 tree "+obj+"\t"+path
        raise AssertionError(args)
    monkeypatch.setattr(runtime,"_git",fake_git)
    monkeypatch.setattr(runtime,"_tool",lambda argv:"mock-version")
    cfg=configuration.default_configuration("cross-engine","stable","Stable")
    first=preparation.source_identity(tmp_path,cfg)
    state["sha"]="b"*40  # Only result JSON / docs were committed.
    second=preparation.source_identity(tmp_path,cfg)
    assert first == second
    state["crate_object"]="e"*40
    third=preparation.source_identity(tmp_path,cfg)
    assert third != first
