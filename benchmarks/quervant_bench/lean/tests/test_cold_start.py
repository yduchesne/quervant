"""Single-lane process-cold startup study: deterministic/stub-only acceptance."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from quervant_bench.lean import artifacts, configuration, runtime, statistics


def _cold_fixture():
    cfg = configuration.default_configuration(
        "cross-engine", "cold-test", "Cold process startup regression",
        regime="process-cold"
    )
    cfg["policy"].update(blocks=6, slots_per_arm=2, samples=3, bootstrap_resamples=100)
    return cfg, configuration.lanes_for(cfg)[0]


def _script(tmp_path, body):
    script = tmp_path / "stub_cold_adapter.py"
    script.write_text(body, encoding="utf-8")
    return [sys.executable, "-u", str(script)]


def test_launch_to_first_reply_keeps_engine_timing_separate(tmp_path):
    cfg, lane = _cold_fixture()
    stub = _script(tmp_path, """
import json, sys, time
r = json.loads(sys.stdin.readline())
reply = {
    "schema": "pr15d-adapter-v1", "engine": "tantivy",
    "request_id": r["request_id"], "status": "ok",
    "total_hits": 1250,
    "doc_ids": [f"d{i:08d}" for i in range(0, 800, 8)],
    "engine_ns": 100
}
print(json.dumps(reply), flush=True)
time.sleep(0.40)  # Deliberate post-reply shutdown delay is outside timed interval.
""")
    wall_ns, engine_ns = runtime.collect_cold_start(
        stub, engine="tantivy", index_dir=tmp_path, lane=lane, config=cfg,
        arm_id="T", cpu=None, request_id="cold:1", timeout=2)
    assert wall_ns >= engine_ns == 100
    assert wall_ns > 100
    assert wall_ns < 300_000_000, "time must stop at first reply, not delayed shutdown"


@pytest.mark.parametrize(("body", "diagnostic"), [
    ("print('not-json',flush=True)", "malformed adapter JSON reply"),
    ("import sys; sys.exit(3)", "closed before first reply"),
    ("""import json,sys
r=json.loads(sys.stdin.readline())
print(json.dumps({"schema":"pr15d-adapter-v1","engine":"tantivy",
    "request_id":r["request_id"],"status":"error"}),flush=True)
""", "disagrees with request"),
])
def test_cold_start_invalid_adapter_replies_fail_closed(tmp_path, body, diagnostic):
    cfg,lane=_cold_fixture()
    stub=_script(tmp_path,body)
    with pytest.raises(runtime.MeasurementBlocked,match=diagnostic):
        runtime.collect_cold_start(
            stub,engine="tantivy",index_dir=tmp_path,lane=lane,config=cfg,
            arm_id="T",cpu=None,request_id="cold:bad",timeout=2)


def test_cold_start_timeout_is_bounded_and_does_not_claim_measurement(tmp_path):
    cfg,lane=_cold_fixture()
    stub=_script(tmp_path,"import time; time.sleep(10)")
    with pytest.raises(runtime.MeasurementBlocked,match="first reply timed out"):
        runtime.collect_cold_start(
            stub,engine="tantivy",index_dir=tmp_path,lane=lane,config=cfg,
            arm_id="T",cpu=None,request_id="cold:timeout",timeout=0.05)


def test_cold_run_has_only_cold_lane_and_skips_serial_throughput(tmp_path,monkeypatch):
    cfg,lane=_cold_fixture()
    path=artifacts.create_configuration(tmp_path/"configs",cfg)
    monkeypatch.setattr(runtime,"create_corpus",lambda p,n:p.write_text("synthetic"))
    monkeypatch.setattr(runtime,"host_context",lambda scratch,check:{"physical_core_candidates":[]})
    def mock_index(*args,**kwargs):
        return {"index_ns":1,"commit_ns":1,"reopen_ns":1,"index_bytes":1,"segment_count":1}
    monkeypatch.setattr(runtime,"collect_throughput",
                        lambda *a,**k:(_ for _ in ()).throw(AssertionError("no warm throughput")))
    def fake_phase(config,lanes,binaries,indexes,*,cpu,on_slot):
        assert len(lanes)==1 and lanes[0]["id"]==lane["id"]
        schedule=statistics.schedule(
            list(config["arms"]),blocks=config["policy"]["blocks"],
            slots_per_arm=config["policy"]["slots_per_arm"],seed=config["policy"]["seed"])
        rows=[{"arm_id":x["arm_id"],"block":x["block"],"position":x["position"],
               "lane_id":lane["id"],"oracle_ok":True,"warmups":0,
               "samples_ns":[200]*3,"engine_samples_ns":[100]*3,
               "overhead_samples_ns":[100]*3} for x in schedule]
        on_slot(rows)
        return rows
    monkeypatch.setattr(runtime,"_phase",fake_phase)
    saved,result=runtime.run_benchmark(
        path,tmp_path/"results",root=tmp_path,
        programs={a:["/mock"] for a in cfg["arms"]},
        check_host=False,index_builder=mock_index)
    assert result["status"]=="COMPLETE"
    assert len(result["lanes"])==1
    assert result["lanes"][0]["metric"]=="cold_start_first_response_latency"
    assert "throughput_metrics" not in result
    assert len(result["raw_samples"])==6*3*2
    assert result["controls"]["analysis"]["lanes"][lane["id"]]
    assert artifacts.load_result(saved)["configuration_id"]==cfg["configuration_id"]
