"""BM-10 deterministic tests: never launch real adapters or run timed benchmarks."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import contextlib
import json
import platform

import pytest

from quervant_bench.lean import artifacts, cli, configuration, reporting, runtime, statistics


def store_config(tmp_path: Path, config: dict) -> Path:
    return artifacts.create_configuration(
        artifacts.configuration_directory(tmp_path / "studies", config), config)


def make_config(tmp_path: Path, *, name="retained-key-demo", family="retained-key") -> tuple[Path, dict]:
    config = configuration.default_configuration(family, name, "A dated benchmark configuration",
                                                  timestamp="2026-11-21T23:55:00Z")
    return store_config(tmp_path, config), config


def raw_result(config, executed="2026-11-22T00:05:00Z"):
    return {"configuration_id": config["configuration_id"], "run_id": str(uuid4()),
            "executed_utc": executed, "raw_samples": [], "analysis": {}, "status": "INCOMPLETE"}


def one_lane():
    return {"id":"L0", "metric": "search_latency", "unit": "ns", "direction": "lower",
            "comparability": "COMPARABLE"}


def sample_rows(arms=("A", "B"), *, blocks=4, reps=2, n=3, values=None, seed=42):
    schedule = statistics.schedule(arms, blocks=blocks, slots_per_arm=reps, seed=seed)
    values = values or {"A":100,"B":80}
    return [{"arm_id":row["arm_id"],"block":row["block"],"position":row["position"],
             "lane_id":"L0","oracle_ok":True,"samples_ns":[values[row["arm_id"]]]*n}
            for row in schedule]


def policy(**changes):
    return {"blocks":4,"slots_per_arm":2,"samples":3,"bootstrap_resamples":1000,
            "seed":42,"min_blocks":4,"min_gain_percent":0,"max_regression_percent":0,
            "max_aa_gain_percent":15,"exclude_blocks":{},"control_arms":[],**changes}


def test_configuration_name_utc_and_schema(tmp_path):
    path, config = make_config(tmp_path)
    assert path.name == "retained-key-demo-2026-11-21.json"
    assert artifacts.load_configuration(path) == config
    for name in ("Bad", "a__b", "-a", "a/../b", "a" * 81, "a-"):
        with pytest.raises(artifacts.ArtifactError):
            configuration.default_configuration("retained-key", name, "description")
    malformed = deepcopy(config)
    malformed["created_utc"] = "2026-02-30T00:00:00Z"
    with pytest.raises(artifacts.ArtifactError):
        artifacts.configuration_filename(malformed)
    for key, value in (("family","random"),("arms",{"A":{}}),("policy",{})):
        malformed = deepcopy(config); malformed[key] = value
        with pytest.raises(artifacts.ArtifactError):
            configuration.validate_configuration(malformed)


def test_configuration_names_unique_across_ids_and_dates(tmp_path):
    first, config = make_config(tmp_path)
    again = deepcopy(config)
    again["configuration_id"] = str(uuid4())
    again["created_utc"] = "2026-11-22T12:00:00Z"
    with pytest.raises(artifacts.ArtifactError,match="name already reserved"):
        artifacts.create_configuration(first.parent, again)
    with pytest.raises(artifacts.ArtifactError,match="name already reserved"):
        artifacts.create_configuration(first.parent, config)


def test_result_cross_date_increment_and_replay(tmp_path):
    path, config = make_config(tmp_path)
    root = path.parent.parent / "results"
    a=artifacts.publish_result(path,root,raw_result(config, "2026-11-21T23:59:00Z"))
    b=artifacts.publish_result(path,root,raw_result(config, "2026-11-22T00:00:00Z"))
    assert a.name.endswith("-2026-11-21-001.json")
    assert b.name.endswith("-2026-11-22-002.json")
    assert artifacts.load_result(b)["configuration_file"] == path.name
    assert artifacts.load_result(b)["sequence"] == 2
    # Incomplete results have a readable report without any statistical derivation.
    assert "INCOMPLETE" in reporting.replay_to_markdown(b)
    with pytest.raises(artifacts.ArtifactError):
        artifacts.publish_result(path, root, {**raw_result(config), "configuration_id":str(uuid4())})


def test_result_collision_concurrency(tmp_path):
    path, config = make_config(tmp_path)
    root=path.parent.parent / "results"
    with ThreadPoolExecutor(max_workers=8) as executor:
        saved = list(executor.map(lambda _:artifacts.publish_result(path,root,raw_result(config)),range(8)))
    assert len({p.name for p in saved}) == 8
    assert sorted(artifacts.load_result(p)["sequence"] for p in saved) == list(range(1,9))
    assert all(p.exists() for p in saved)


def test_result_missing_malformed_or_symlink_refused(tmp_path):
    path, config=make_config(tmp_path)
    output=path.parent.parent/"results"
    saved=artifacts.publish_result(path,output,raw_result(config))
    corrupt=output/"copy.json"
    corrupt.write_text('{"x":1,"x":2}')
    with pytest.raises(artifacts.ArtifactError):
        artifacts.publish_result(path,output,raw_result(config))
    corrupt.unlink()
    fake=output/"fake.json"
    fake.symlink_to(saved)
    with pytest.raises(artifacts.ArtifactError):
        artifacts.load_result(fake)


def test_schedule_balance_reproducible_and_invalid():
    for arms in (("A","B"),("A","L","P","H"),("Q","T","J")):
        s=statistics.schedule(arms, blocks=12,slots_per_arm=2,seed=98)
        assert len(s)==12*len(arms)*2
        assert s==statistics.schedule(arms, blocks=12,slots_per_arm=2,seed=98)
        for b in range(1,13):
            assert sorted(x["arm_id"] for x in s if x["block"] == b)==sorted(list(arms)*2)
        for position in range(1,2*len(arms)+1):
            ids=[x["arm_id"] for x in s if x["position"]==position]
            assert len(set(ids))==len(arms)
    with pytest.raises(artifacts.ArtifactError):
        statistics.schedule(("A","A"), blocks=4,slots_per_arm=2,seed=0)
    with pytest.raises(artifacts.ArtifactError):
        statistics.schedule(("A","B"), blocks=3,slots_per_arm=2,seed=0)


def test_paired_math_direction_and_outcomes():
    result=statistics.analyze(sample_rows(),arms=["A","B"],baseline="A",lanes=[one_lane()],policy=policy())
    b=result["lanes"]["L0"]["comparisons"]["B"]
    assert b["ratio_b_over_a"]==.8
    assert b["gain_percent"]==20
    assert b["status"]=="IMPROVED"
    assert b["ratio_ci_95"]==[.8,.8]
    higher={**one_lane(),"direction":"higher","metric":"throughput","unit":"ops_per_second"}
    result=statistics.analyze(sample_rows(values={"A":100,"B":120}),arms=["A","B"],baseline="A",lanes=[higher],policy=policy())
    assert result["lanes"]["L0"]["comparisons"]["B"]["gain_percent"]==20


def test_paired_median_not_pooled_ratio_and_exclusions():
    samples=sample_rows()
    for row in samples:
        if row["block"]==4:
            row["samples_ns"]=[1000 if row["arm_id"]=="A" else 100]*3
    result=statistics.analyze(samples,arms=["A","B"],baseline="A",lanes=[one_lane()],policy=policy())
    assert result["lanes"]["L0"]["comparisons"]["B"]["ratio_b_over_a"]==.8
    x=statistics.analyze(samples,arms=["A","B"],baseline="A",lanes=[one_lane()],policy=policy(exclude_blocks={"L0":[4]}))
    assert x["lanes"]["L0"]["retained_blocks"]==3
    assert x["lanes"]["L0"]["comparisons"]["B"]["status"]=="INCONCLUSIVE"
    assert len(x["lanes"]["L0"]["arm_absolute"]["A"]["block_values"])==4


def test_cannot_analyze_missing_duplicate_oracle_or_bad_time():
    rows=sample_rows()
    for altered in (rows[:-1], rows+[rows[0]], [{**rows[0],"oracle_ok":False},*rows[1:]],
                    [{**rows[0],"samples_ns":[True,1,1]},*rows[1:]],
                    [{**rows[0],"samples_ns":[-1,1,1]},*rows[1:]]):
        with pytest.raises(artifacts.ArtifactError):
            statistics.analyze(altered,arms=["A","B"],baseline="A",lanes=[one_lane()],policy=policy())


def test_aa_rejects_unstable_control():
    control=statistics.analyze(sample_rows(arms=("AA","AA2"), values={"AA":100,"AA2":200}),
                               arms=["AA","AA2"],baseline="AA",lanes=[one_lane()],
                               policy=policy(control_arms=["AA2"]))
    assert control["lanes"]["L0"]["comparisons"]["AA2"]["status"]=="FAIL"


def test_non_comparable_no_numeric_ratio():
    lane={**one_lane(),"comparability":"NON_COMPARABLE","reason":"timing boundaries differ"}
    x=statistics.analyze(sample_rows(),arms=["A","B"],baseline="A",lanes=[lane],policy=policy())
    v=x["lanes"]["L0"]["comparisons"]["B"]
    assert v["status"]=="NON_COMPARABLE" and "ratio_b_over_a" not in v


def test_historical_pp_and_context_change():
    cur={"status":"COMPLETE",
         "analysis":statistics.analyze(sample_rows(),arms=["A","B"],baseline="A",lanes=[one_lane()],policy=policy()),
         "raw_samples":sample_rows(),
         "controls":{"analysis":{"lanes":{"L0":{"comparisons":{"AA2":{"status":"PASS"}}}}}},
         "lanes":[{"id":"L0","workload_id":"x","cache_regime":"warm","timed_operation":"exact","query_semantics":"same"}],
         "context":{"host":"a"}}
    hist=deepcopy(cur)
    assert statistics.compare_historical(cur,None,lane_id="L0",treatment_arm="B")["status"]=="UNAVAILABLE"
    assert statistics.compare_historical(cur,hist,lane_id="L0",treatment_arm="B")["effect_change_percentage_points"]==0
    hist["context"]={"host":"b"}
    assert statistics.compare_historical(cur,hist,lane_id="L0",treatment_arm="B")["status"]=="CONTEXT_CHANGED"
    hist["lanes"][0]["cache_regime"]="cold"
    assert statistics.compare_historical(cur,hist,lane_id="L0",treatment_arm="B")["status"]=="NOT_COMPARABLE"


def test_reporting_never_analyzes(monkeypatch,tmp_path):
    path,config=make_config(tmp_path)
    data=raw_result(config)
    data["analysis"]={"estimator":"saved-only","bootstrap_method":"none","lanes":{
        "lane": {"metric":"search_latency","unit":"ns","direction":"lower",
                 "arm_absolute":{"A":{"median_block_value":100}},"comparisons":{}}}}
    dest=artifacts.publish_result(path,path.parent.parent/"results",data)
    monkeypatch.setattr(statistics,"analyze",lambda *args,**kw:(_ for _ in ()).throw(AssertionError("analyzer invoked")))
    assert "saved-only" in reporting.replay_to_markdown(dest)
    assert "lane" in reporting.replay_to_markdown(dest)


def test_cli_has_no_receipt_verbs():
    commands=cli.parser()._subparsers._group_actions[0].choices
    assert set(commands)=={"prepare","stage","run","validate","analyze","compare","report","replay"}
    for retired in ("accept","verify","inspect","certify","seal"):
        with pytest.raises(SystemExit) as error:
            cli.main([retired])
        assert error.value.code==2


def test_runtime_retains_partial_result_and_no_timed_test(tmp_path,monkeypatch):
    path,cfg=make_config(tmp_path)
    cfg=deepcopy(cfg)
    cfg["policy"].update(samples=3,bootstrap_resamples=100)
    path.unlink(); artifacts.create_configuration(path.parent,cfg)
    small=configuration.lanes_for(cfg)[:1]
    monkeypatch.setattr(runtime,"lanes_for",lambda config:small)
    monkeypatch.setattr(runtime,"create_corpus",lambda path,n:path.write_text("mock corpus"))
    monkeypatch.setattr(runtime,"host_context",lambda scratch,check: {"physical_core_candidates":[],"filesystem":"mock"})
    arm_values={"A":100,"L":90,"P":80,"H":110,"AA":100,"AA2":100}
    def fake_phase(config,lanes,binaries,indexes,*,cpu,on_slot):
        rows=statistics.schedule(list(config["arms"]),blocks=config["policy"]["blocks"],
                                 slots_per_arm=config["policy"]["slots_per_arm"],seed=cfg["policy"]["seed"])
        result=[]
        for x in rows:
            r={"arm_id":x["arm_id"],"block":x["block"],"position":x["position"],
               "lane_id":lanes[0]["id"],"oracle_ok":True,
               "samples_ns":[arm_values[x["arm_id"]]]*cfg["policy"]["samples"]}
            result.append(r)
            on_slot([r])
        return result
    def fake_index(*args,**kwargs): return {"index_ns":1,"commit_ns":1,"index_bytes":1,"reopen_ns":1,"segment_count":1}
    result_path, r=runtime.run_benchmark(path,path.parent.parent/"results",root=tmp_path,
                                      programs={a:["/mock"] for a in cfg["arms"]},check_host=False,
                                      invoke_phase=fake_phase,index_builder=fake_index)
    assert result_path.exists() and r["status"]=="COMPLETE"
    assert len(r["raw_samples"]) == cfg["policy"]["blocks"]*len(cfg["arms"])*cfg["policy"]["slots_per_arm"]
    assert r["analysis"]["lanes"][small[0]["id"]]["comparisons"]["P"]["ratio_b_over_a"]==.8
    # Rerun with failure after part of the first treatment slot and verify the
    # result alone preserves completed control + partial samples + diagnosis.
    def failing_phase(config,lanes,binaries,indexes,*,cpu,on_slot):
        if "AA" in config["arms"]:
            return fake_phase(config,lanes,binaries,indexes,cpu=cpu,on_slot=on_slot)
        on_slot([{"arm_id":"A","block":1,"position":1,"lane_id":lanes[0]["id"],"oracle_ok":True,"samples_ns":[100]*3}])
        raise runtime.MeasurementBlocked("mock runtime interruption")
    result_path, r=runtime.run_benchmark(path,path.parent.parent/"results",root=tmp_path,
                                       programs={a:["/mock"] for a in cfg["arms"]},check_host=False,
                                       invoke_phase=failing_phase,index_builder=fake_index)
    assert r["status"]=="INCOMPLETE" and len(r["raw_samples"])==1
    assert "mock runtime interruption" in r["errors"][0]
    assert "INCOMPLETE" in reporting.replay_to_markdown(result_path)
    assert artifacts.load_result(result_path)["sequence"]==2


def fake_reply(engine, req, *, n=10000):
    expected = runtime.expected_answer(n, req.get("field", "key"), req.get("term", "never"), req.get("k", 10))
    return {"schema":runtime.ADAPTER_SCHEMA,"engine":engine,"request_id":req["request_id"],
            "status":"ok","total_hits":expected[0],"doc_ids":expected[1],"engine_ns":100}


def test_independent_corpus_formula_and_oracle(tmp_path):
    path=tmp_path/"corpus.tsv"
    runtime.create_corpus(path,10000)
    text=path.read_text()
    assert text.startswith(runtime.HEADER)
    assert text.count("\n")==10001
    assert "\tcommon\tmedium\t" in text
    assert runtime.expected_answer(10000,"key","never",10)==(0,[])
    assert runtime.expected_answer(10000,"key","singleton",10)==(1,["d00000000"])
    assert runtime.expected_answer(10000,"group","medium",10)[0]==1250
    assert runtime.expected_answer(10000,"key","common",10)[0]==4999
    with pytest.raises(runtime.MeasurementBlocked):
        runtime.create_corpus(tmp_path/"bad",12)
    with pytest.raises(runtime.MeasurementBlocked):
        runtime.expected_answer(10000,"body","alpha",10)


def test_adapter_reply_oracle_and_metadata_rejections():
    lane={"id":"lane","n":10000,"field":"key","term":"never","k":10,"cache_regime":"warm"}
    req={"request_id":"q1","field":"key","term":"never","k":10}
    good=fake_reply("tantivy",req)
    assert runtime.validate_reply(good,lane,(0,[]))==100
    for key,value in (("engine_ns",True),("engine_ns",0),("total_hits",1),("doc_ids",["d00000001"])):
        bad={**good,key:value}
        with pytest.raises(runtime.MeasurementBlocked):runtime.validate_reply(bad,lane,(0,[]))
    import subprocess
    done=subprocess.CompletedProcess([],0,json.dumps(good)+"\n","")
    assert runtime._decode_responses(done,[req],engine="tantivy")==[good]
    with pytest.raises(runtime.MeasurementBlocked):
        runtime._decode_responses(done,[req,req],engine="tantivy")
    with pytest.raises(runtime.MeasurementBlocked):
        runtime._decode_responses(subprocess.CompletedProcess([],0,'not-json\n',""),[req],engine="tantivy")
    with pytest.raises(runtime.MeasurementBlocked):
        runtime._decode_responses(done,[req],engine="lucene")


def test_strategy_markers_mandatory_and_proved(monkeypatch):
    import subprocess
    cfg=configuration.default_configuration("cross-engine","cross-demo","Three adapters")
    assert cfg["build"]["quervant_feature"] is None
    # Simulate poisoned operator environment. Cross-engine must benchmark the
    # true compiled production default, never an experimental strategy override.
    monkeypatch.setenv("QUERVANT_PR15I_D3C_STRATEGY", "exact_set")
    monkeypatch.setenv("QUERVANT_PR15I_D3C_PREFILTER_PROFILE", "P0")
    for k in (10, 32, 100):
        env,marker=runtime._strategy(cfg,"Q",{"k":k})
        assert marker is None
        assert "QUERVANT_PR15I_D3C_STRATEGY" not in env
        assert "QUERVANT_PR15I_D3C_PREFILTER_PROFILE" not in env
    retained=configuration.default_configuration("retained-key","retained-demo","Four arms")
    env,marker=runtime._strategy(retained,"P",{"k":100})
    assert marker=="PR15I_D3C_MODE=v1:prefilter:P2"
    assert env["QUERVANT_PR15I_D3C_PREFILTER_PROFILE"]=="P2"
    done=subprocess.CompletedProcess([],0,"", "PR15I_D3C_MODE=v1:prefilter:P2\n")
    runtime._check_marker(done,"PR15I_D3C_MODE=v1:prefilter:P2",engine="quervant")
    with pytest.raises(runtime.MeasurementBlocked):
        runtime._check_marker(done,None,engine="quervant")
    with pytest.raises(runtime.MeasurementBlocked):
        runtime._check_marker(done,"PR15I_D3C_MODE=v1:linear:none",engine="quervant")
    runtime._check_marker(done,None,engine="tantivy")



def test_cross_engine_production_default_rejects_experiment_feature():
    cfg=configuration.default_configuration("cross-engine","prod-default","Production baseline")
    assert cfg["arms"]["Q"]["mode"]=="by-top-k"
    assert cfg["build"]["quervant_feature"] is None
    altered=deepcopy(cfg)
    altered["build"]["quervant_feature"]="quervant-core/pr15i-d3c-experiment"
    with pytest.raises(artifacts.ArtifactError,match="restricted to retained-key"):
        configuration.validate_configuration(altered)



def test_versioned_cross_engine_configs_are_separate_and_immutable():
    studies_root=Path(__file__).resolve().parents[3]/"studies"
    warm_path=studies_root/"cross-engine"/"warm"/"configurations"/"quervant-tantivy-lucene-warm-2026-11-22.json"
    cold_path=studies_root/"cross-engine"/"cold-start"/"configurations"/"quervant-tantivy-lucene-cold-start-2026-11-22.json"
    warm=artifacts.load_configuration(warm_path)
    cold=artifacts.load_configuration(cold_path)
    for cfg in (warm,cold):
        configuration.validate_configuration(cfg)
        assert cfg["family"]=="cross-engine"
        assert cfg["baseline"]=="Q"
        assert cfg["arms"]["Q"]=={"engine":"quervant","mode":"by-top-k","source":"current"}
        assert cfg["build"]["quervant_feature"] is None
    assert warm["configuration_id"]!=cold["configuration_id"]
    assert warm["workload"]["regimes"]==["warm"]
    assert cold["workload"]["regimes"]==["process-cold"]
    assert cold["workload"]["sizes"]==[10000]
    assert cold["workload"]["classes"]==["medium"]
    assert cold["workload"]["top_k"]==[100]
    assert len(configuration.lanes_for(warm))==16
    cold_lanes=configuration.lanes_for(cold)
    assert len(cold_lanes)==1
    assert cold_lanes[0]["id"]=="10000/medium/k100/process-cold"
    assert cold_lanes[0]["metric"]=="cold_start_first_response_latency"
    assert cold_lanes[0]["timed_operation"]=="process-launch-to-first-jsonl-response"
    assert not (studies_root.parent/"configurations").exists()
    assert not (studies_root/"retained-key"/"cold-start").exists()


def test_cross_engine_cold_policy_is_restricted_to_one_lane():
    cold=configuration.default_configuration("cross-engine","cold","Cold startup",regime="process-cold")
    for field,value in (("sizes",[10000,100000]),("classes",["rare","medium"]),
                        ("top_k",[10,100]),("regimes",["warm","process-cold"]),
                        ("timed_operation","exact-term-search-plus-topk-projection")):
        variant=deepcopy(cold)
        variant["workload"][field]=value
        with pytest.raises(artifacts.ArtifactError):
            configuration.validate_configuration(variant)
    with pytest.raises(artifacts.ArtifactError):
        configuration.default_configuration("retained-key","wrong","No cold retained key",
                                            regime="process-cold")

def test_build_index_mock_success_and_failures(tmp_path,monkeypatch):
    import subprocess
    def build_response(n=10000, ns=123, size=2048):
        return {"schema":runtime.ADAPTER_SCHEMA,"engine":"quervant","request_id":"build",
                "status":"ok","documents_indexed":n,"documents_verified":n,
                "index_ns":ns,"commit_ns":10,"reopen_ns":3,"index_bytes":size,"segment_count":2}
    reply=build_response()
    monkeypatch.setattr(runtime,"_run_pinned",lambda *a,**kw:subprocess.CompletedProcess([],0,json.dumps(reply)+"\n",""))
    monkeypatch.setattr(runtime,"_index_size",lambda *a:2048)
    result=runtime.build_index(["/not-real"],engine="quervant", corpus_path=tmp_path/"input",
                               target=tmp_path/"index",n=10000,cpu=None)
    assert result["index_bytes"]==2048
    with pytest.raises(FileExistsError):
        runtime.build_index(["/not-real"],engine="quervant", corpus_path=tmp_path/"input",
                            target=tmp_path/"index",n=10000,cpu=None)
    reply["documents_verified"]=9
    with pytest.raises(runtime.MeasurementBlocked):
        runtime.build_index(["/not-real"],engine="quervant", corpus_path=tmp_path/"input",
                            target=tmp_path/"index2",n=10000,cpu=None)
    reply.update(documents_verified=10000,index_ns=0)
    with pytest.raises(runtime.MeasurementBlocked):
        runtime.build_index(["/not-real"],engine="quervant", corpus_path=tmp_path/"input",
                            target=tmp_path/"index3",n=10000,cpu=None)
    reply["index_ns"]=123
    monkeypatch.setattr(runtime,"_index_size",lambda *a:2047)
    with pytest.raises(runtime.MeasurementBlocked):
        runtime.build_index(["/not-real"],engine="quervant", corpus_path=tmp_path/"input",
                            target=tmp_path/"index4",n=10000,cpu=None)


def test_collect_slot_both_regimes_mocked_adapter(monkeypatch,tmp_path):
    import subprocess
    warm=configuration.default_configuration("cross-engine","warm-demo","Warm study")
    cold=configuration.default_configuration("cross-engine","cold-demo","Cold study",
                                             regime="process-cold")
    warm["policy"].update(samples=3,warmups=2)
    cold["policy"].update(samples=3,warmups=2)
    warm_lane=next(x for x in configuration.lanes_for(warm)
                   if x["id"]=="10000/medium/k100/warm")
    cold_lane=configuration.lanes_for(cold)[0]
    calls=[]
    def fake_process(argv,cpu,*,env,input_text,timeout):
        requests=[json.loads(t) for t in input_text.splitlines()]
        calls.append(("warm",len(requests),cpu))
        payload="".join(json.dumps(fake_reply("tantivy",r))+"\n" for r in requests)
        return subprocess.CompletedProcess(argv,0,payload,"")
    def fake_cold(command,*,engine,index_dir,lane,config,arm_id,cpu,request_id,timeout=120):
        assert engine=="tantivy" and lane["id"]==cold_lane["id"]
        calls.append(("cold",request_id,cpu))
        return (300,150,100)
    monkeypatch.setattr(runtime,"_run_pinned",fake_process)
    monkeypatch.setattr(runtime,"collect_cold_start",fake_cold)
    w=runtime.collect_slot(warm,"T",[warm_lane],["fake"],{10000:tmp_path},
                           block=3,position=2,cpu=5)
    c=runtime.collect_slot(cold,"T",[cold_lane],["fake"],{10000:tmp_path},
                           block=3,position=2,cpu=5)
    assert len(w)==len(c)==1
    assert w[0]["samples_ns"]==[100]*3 and w[0]["warmups"]==2
    assert c[0]["samples_ns"]==[300]*3 and c[0]["warmups"]==0
    assert c[0]["index_open_samples_ns"]==[150]*3
    assert c[0]["engine_samples_ns"]==[100]*3
    assert c[0]["other_overhead_samples_ns"]==[50]*3
    assert [x[0] for x in calls]==["warm","cold","cold","cold"]
    assert all(x[2]==5 for x in calls)
    assert all(x["oracle_ok"] for x in [*w,*c])


def test_collect_throughput_with_fake_jsonl_child(tmp_path):
    import sys
    script=tmp_path/"fake_adapter.py"
    script.write_text('''import json,sys
for line in sys.stdin:
    r=json.loads(line)
    x={"schema":"pr15d-adapter-v1","engine":"tantivy", "request_id":r["request_id"],
       "status":"ok","total_hits":0,"doc_ids":[],"engine_ns":10}
    print(json.dumps(x),flush=True)
''')
    cfg=configuration.default_configuration("cross-engine","cross-demo","Three adapters")
    cfg["policy"]["warmups"]=2
    lane={"id":"10k-absent","n":10000,"field":"key","term":"never","k":10}
    result=runtime.collect_throughput([sys.executable,"-u",str(script)],engine="tantivy",
                                      index_dir=tmp_path, lane=lane,config=cfg,arm_id="T",cpu=None,requests=3)
    assert result["requests"]==3 and result["warmups"]==2
    assert result["serial_ops_per_second"]>0 and result["status"]=="MEASURED"
    script.write_text('raise SystemExit(7)\n')
    with pytest.raises(runtime.MeasurementBlocked):
        runtime.collect_throughput([sys.executable,"-u",str(script)],engine="tantivy",
                                   index_dir=tmp_path,lane=lane,config=cfg,arm_id="T",cpu=None,requests=2)


def test_collect_throughput_rejects_malformed_or_mismatched_replies(tmp_path):
    # I-11: an unparseable or schema/status-mismatched reply fails closed instead
    # of contributing an unverified timed window.
    import sys
    cfg=configuration.default_configuration("cross-engine","cross-demo","Three adapters")
    cfg["policy"]["warmups"]=0
    lane={"id":"10k-absent","n":10000,"field":"key","term":"never","k":10}
    script=tmp_path/"bad_adapter.py"
    for body,match in (
        ('import sys\nsys.stdin.readline()\nprint("not-json",flush=True)\n',"malformed throughput"),
        ('import json,sys\nr=json.loads(sys.stdin.readline())\n'
         'print(json.dumps({"schema":"pr15d-adapter-v1","engine":"tantivy",'
         '"request_id":r["request_id"],"status":"error"}),flush=True)\n',"reply mismatch"),
    ):
        script.write_text(body)
        with pytest.raises(runtime.MeasurementBlocked,match=match):
            runtime.collect_throughput([sys.executable,"-u",str(script)],engine="tantivy",
                                       index_dir=tmp_path,lane=lane,config=cfg,arm_id="T",cpu=None,requests=1)


def test_run_benchmark_blocks_treatment_after_unstable_control(tmp_path,monkeypatch):
    # I-09: an unstable A/A control stops acquisition; no treatment samples are
    # claimed and the diagnostic is preserved in the single INCOMPLETE result.
    path,cfg=make_config(tmp_path)
    cfg=deepcopy(cfg); cfg["policy"].update(samples=3,bootstrap_resamples=100)
    path.unlink(); artifacts.create_configuration(path.parent,cfg)
    monkeypatch.setattr(runtime,"lanes_for",lambda config:configuration.lanes_for(cfg)[:1])
    monkeypatch.setattr(runtime,"create_corpus",lambda p,n:p.write_text("mock"))
    monkeypatch.setattr(runtime,"host_context",
                        lambda scratch,check:{"physical_core_candidates":[(0,0,0),(1,0,1)]})
    monkeypatch.setattr(runtime,"assess_readiness",lambda *a,**k:{"status":"clear","observations":[]})
    monkeypatch.setattr(runtime,"pinned_controller",lambda cpu:contextlib.nullcontext())
    values={"A":100,"L":100,"P":100,"H":100,"AA":100,"AA2":260}
    def fake_phase(config,lanes,binaries,indexes,*,cpu,on_slot):
        rows=statistics.schedule(list(config["arms"]),blocks=config["policy"]["blocks"],
                                 slots_per_arm=config["policy"]["slots_per_arm"],seed=cfg["policy"]["seed"])
        out=[{"arm_id":x["arm_id"],"block":x["block"],"position":x["position"],
              "lane_id":lanes[0]["id"],"oracle_ok":True,"samples_ns":[values[x["arm_id"]]]*3}
             for x in rows]
        on_slot(out)
        return out
    def fake_index(*args,**kwargs): return {"index_ns":1,"commit_ns":1,"index_bytes":1,"reopen_ns":1,"segment_count":1}
    _,r=runtime.run_benchmark(path,path.parent.parent/"results",root=tmp_path,
                              programs={a:["/mock"] for a in cfg["arms"]},check_host=True,
                              invoke_phase=fake_phase,index_builder=fake_index)
    assert r["status"]=="INCOMPLETE"
    assert any("A/A control is unstable" in e for e in r["errors"])
    assert r["raw_samples"]==[] and r["analysis"]=={}
    assert "readiness_pre" in r["controls"]


def test_run_benchmark_stops_on_busy_host_before_control(tmp_path,monkeypatch):
    # I-14: host contention fails closed before any A/A or treatment acquisition.
    path,cfg=make_config(tmp_path)
    cfg=deepcopy(cfg); cfg["policy"].update(samples=3,bootstrap_resamples=100)
    path.unlink(); artifacts.create_configuration(path.parent,cfg)
    monkeypatch.setattr(runtime,"lanes_for",lambda config:configuration.lanes_for(cfg)[:1])
    monkeypatch.setattr(runtime,"create_corpus",lambda p,n:p.write_text("mock"))
    monkeypatch.setattr(runtime,"host_context",
                        lambda scratch,check:{"physical_core_candidates":[(0,0,0),(1,0,1)]})
    readiness_sequence(monkeypatch,["clear","busy"])
    monkeypatch.setattr(runtime,"pinned_controller",lambda cpu:contextlib.nullcontext())
    def never(*args,**kwargs): raise AssertionError("acquisition must not start on a busy host")
    def fake_index(*args,**kwargs): return {"index_ns":1,"commit_ns":1,"index_bytes":1,"reopen_ns":1,"segment_count":1}
    _,r=runtime.run_benchmark(path,path.parent.parent/"results",root=tmp_path,
                              programs={a:["/mock"] for a in cfg["arms"]},check_host=True,
                              invoke_phase=never,index_builder=fake_index)
    assert r["status"]=="INCOMPLETE"
    assert any("host contention before A/A" in e for e in r["errors"])
    assert r["raw_samples"]==[] and r["controls"]["readiness_pre"]["status"]=="busy"


def readiness_sequence(monkeypatch,statuses):
    pending=iter(statuses)
    monkeypatch.setattr(runtime,"assess_readiness",lambda *a,**k:{"status":next(pending),"observations":[]})


def test_run_benchmark_blocks_treatment_on_contention_after_clean_control(tmp_path,monkeypatch):
    # I-14: contention observed before treatment stops acquisition; the passing
    # control is retained as diagnostic but no treatment samples are claimed.
    path,cfg=make_config(tmp_path)
    cfg=deepcopy(cfg); cfg["policy"].update(samples=3,bootstrap_resamples=100)
    path.unlink(); artifacts.create_configuration(path.parent,cfg)
    monkeypatch.setattr(runtime,"lanes_for",lambda config:configuration.lanes_for(cfg)[:1])
    monkeypatch.setattr(runtime,"create_corpus",lambda p,n:p.write_text("mock"))
    monkeypatch.setattr(runtime,"host_context",
                        lambda scratch,check:{"physical_core_candidates":[(0,0,0),(1,0,1)]})
    monkeypatch.setattr(runtime,"pinned_controller",lambda cpu:contextlib.nullcontext())
    readiness_sequence(monkeypatch,["clear","clear","busy"])
    values={"A":100,"L":90,"P":80,"H":110,"AA":100,"AA2":100}
    def fake_phase(config,lanes,binaries,indexes,*,cpu,on_slot):
        rows=statistics.schedule(list(config["arms"]),blocks=config["policy"]["blocks"],
                                 slots_per_arm=config["policy"]["slots_per_arm"],seed=cfg["policy"]["seed"])
        out=[{"arm_id":x["arm_id"],"block":x["block"],"position":x["position"],
              "lane_id":lanes[0]["id"],"oracle_ok":True,"samples_ns":[values[x["arm_id"]]]*3} for x in rows]
        on_slot(out)
        return out
    def fake_index(*args,**kwargs): return {"index_ns":1,"commit_ns":1,"index_bytes":1,"reopen_ns":1,"segment_count":1}
    _,r=runtime.run_benchmark(path,path.parent.parent/"results",root=tmp_path,
                              programs={a:["/mock"] for a in cfg["arms"]},check_host=True,
                              invoke_phase=fake_phase,index_builder=fake_index)
    assert r["status"]=="INCOMPLETE"
    assert any("host contention before treatment" in e for e in r["errors"])
    assert r["raw_samples"]==[] and r["analysis"]=={}
    assert r["controls"]["readiness_pre"]["status"]=="clear"
    assert r["controls"]["readiness_treatment"]["status"]=="busy"
    assert r["controls"]["analysis"]["lanes"]


def test_run_benchmark_preserves_samples_but_invalidates_on_post_contention(tmp_path,monkeypatch):
    # I-04: completed observations are retained while the run is marked INCOMPLETE
    # and never presented as accepted performance.
    path,cfg=make_config(tmp_path)
    cfg=deepcopy(cfg); cfg["policy"].update(samples=3,bootstrap_resamples=100)
    path.unlink(); artifacts.create_configuration(path.parent,cfg)
    monkeypatch.setattr(runtime,"lanes_for",lambda config:configuration.lanes_for(cfg)[:1])
    monkeypatch.setattr(runtime,"create_corpus",lambda p,n:p.write_text("mock"))
    monkeypatch.setattr(runtime,"host_context",
                        lambda scratch,check:{"physical_core_candidates":[(0,0,0),(1,0,1)]})
    monkeypatch.setattr(runtime,"pinned_controller",lambda cpu:contextlib.nullcontext())
    readiness_sequence(monkeypatch,["clear","clear","clear","busy"])
    values={"A":100,"L":90,"P":80,"H":110,"AA":100,"AA2":100}
    def fake_phase(config,lanes,binaries,indexes,*,cpu,on_slot):
        rows=statistics.schedule(list(config["arms"]),blocks=config["policy"]["blocks"],
                                 slots_per_arm=config["policy"]["slots_per_arm"],seed=cfg["policy"]["seed"])
        out=[{"arm_id":x["arm_id"],"block":x["block"],"position":x["position"],
              "lane_id":lanes[0]["id"],"oracle_ok":True,"samples_ns":[values[x["arm_id"]]]*3} for x in rows]
        on_slot(out)
        return out
    def fake_index(*args,**kwargs): return {"index_ns":1,"commit_ns":1,"index_bytes":1,"reopen_ns":1,"segment_count":1}
    saved,r=runtime.run_benchmark(path,path.parent.parent/"results",root=tmp_path,
                                  programs={a:["/mock"] for a in cfg["arms"]},check_host=True,
                                  invoke_phase=fake_phase,index_builder=fake_index)
    assert r["status"]=="INCOMPLETE"
    assert any("after treatment" in e for e in r["errors"])
    assert len(r["raw_samples"])==cfg["policy"]["blocks"]*len(cfg["arms"])*cfg["policy"]["slots_per_arm"]
    assert artifacts.load_result(saved)["raw_samples"]==r["raw_samples"]
    assert "INCOMPLETE" in reporting.replay_to_markdown(saved)


def test_cli_run_reports_incomplete_exit_code_without_benchmark(tmp_path,monkeypatch,capsys):
    # I-04: an incomplete acquisition is a stored result with a distinct exit
    # status, not a silent success or a framework crash.
    path,cfg=make_config(tmp_path)
    monkeypatch.setattr(cli,"run_benchmark",lambda *a,**k:(path.parent.parent/"results"/"r.json",{"status":"INCOMPLETE"}))
    monkeypatch.setattr(cli,"replay_to_markdown",lambda location:"# Incomplete\n")
    assert cli.main(["run","--config",str(path)])==4
    assert "RESULT_JSON=" in capsys.readouterr().out
    monkeypatch.setattr(cli,"run_benchmark",lambda *a,**k:(path.parent.parent/"results"/"r.json",{"status":"COMPLETE"}))
    assert cli.main(["run","--config",str(path)])==0


def test_cli_reports_actionable_error_for_missing_config(tmp_path,capsys):
    assert cli.main(["validate","--config",str(tmp_path/"absent.json")])==2
    assert "BM10_ERROR" in capsys.readouterr().err


def test_cross_engine_run_labels_separate_serial_throughput(tmp_path,monkeypatch):
    # I-13/I-11: throughput is a separately labelled serial session measured for
    # every arm, never derived from engine latency samples.
    cfg=configuration.default_configuration("cross-engine","cross-demo","Three adapters",
                                            timestamp="2026-11-21T23:55:00Z")
    cfg["policy"].update(samples=3,bootstrap_resamples=100)
    path=store_config(tmp_path,cfg)
    lanes=[lane for lane in configuration.lanes_for(cfg)
           if lane["id"] in ("10000/absent/k10/warm","10000/medium/k10/warm")]
    monkeypatch.setattr(runtime,"lanes_for",lambda config:lanes)
    monkeypatch.setattr(runtime,"create_corpus",lambda p,n:p.write_text("mock"))
    monkeypatch.setattr(runtime,"host_context",lambda scratch,check:{"physical_core_candidates":[]})
    values={"Q":100,"T":120,"J":130,"AA":100,"AA2":100}
    def fake_phase(config,lanes,binaries,indexes,*,cpu,on_slot):
        rows=statistics.schedule(list(config["arms"]),blocks=config["policy"]["blocks"],
                                 slots_per_arm=config["policy"]["slots_per_arm"],seed=cfg["policy"]["seed"])
        out=[{"arm_id":x["arm_id"],"block":x["block"],"position":x["position"],
              "lane_id":lane["id"],"oracle_ok":True,"samples_ns":[values[x["arm_id"]]]*3}
             for x in rows for lane in lanes]
        on_slot(out)
        return out
    monkeypatch.setattr(runtime,"_phase",fake_phase)
    calls=[]
    def fake_throughput(command,*,engine,index_dir,lane,config,arm_id,cpu,requests=100):
        calls.append((arm_id,engine,lane["id"],cpu))
        return {"lane_id":lane["id"],"requests":requests,"warmups":config["policy"]["warmups"],
                "wall_ns":1,"serial_ops_per_second":1.0,"status":"MEASURED",
                "timing_scope":"serial session"}
    monkeypatch.setattr(runtime,"collect_throughput",fake_throughput)
    def fake_index(*args,**kwargs): return {"index_ns":1,"commit_ns":1,"index_bytes":1,"reopen_ns":1,"segment_count":1}
    saved,r=runtime.run_benchmark(path,path.parent.parent/"results",root=tmp_path,
                                  programs={a:["/mock"] for a in cfg["arms"]},check_host=False,
                                  index_builder=fake_index)
    assert r["status"]=="COMPLETE"
    assert sorted(c[0] for c in calls)==["J","Q","T"] and len(calls)==3
    assert all(c[2]=="10000/medium/k10/warm" for c in calls)
    assert all(v["status"]=="MEASURED" for v in r["throughput_metrics"].values())
    assert "## Serial throughput" in reporting.replay_to_markdown(saved)
    assert r["analysis"]["lanes"]["10000/absent/k10/warm"]["comparisons"]["T"]["status"]=="REGRESSED", (
        "a slower candidate is valid completed evidence")



def test_corpus_reproduces_independent_oracle_per_class(tmp_path):
    # I-11: derive the expected answer from the corpus file itself, not from
    # expected_answer's own formula, so a wrong oracle cannot agree with itself.
    path=tmp_path/"corpus.tsv"
    runtime.create_corpus(path,10000)
    lines=path.read_text().splitlines()
    assert lines[0].split("\t")==["doc_id","key","group","body","payload"]
    rows=[line.split("\t") for line in lines[1:]]
    assert len(rows)==10000
    for cls,(field,term) in configuration.CLASSES.items():
        index={"key":1,"group":2}[field]
        matched=[row for row in rows if row[index]==term]
        for k in (1,10,1024):
            assert runtime.expected_answer(10000,field,term,k)==(
                len(matched),[row[0] for row in matched[:k]]), cls
    assert configuration.CLASSES["absent"]==("key","never")


def test_slot_median_then_block_mean_is_the_estimator():
    # I-07: each arm/block value is the mean of its slot medians, not the
    # median of pooled samples (8 here versus a pooled median of 7).
    schedule=statistics.schedule(("A","B"),blocks=4,slots_per_arm=2,seed=7)
    custom={("A",1):[[2,4,100],[10,12,14]],("B",1):[[1,1,1],[1,1,1]],("B",2):[[1,1,1],[2,2,2]]}
    counters:dict[tuple[str,int],int]={}
    rows=[]
    for item in schedule:
        key=(item["arm_id"],item["block"])
        occurrence=counters.get(key,0); counters[key]=occurrence+1
        fallback=[100,100,100] if item["arm_id"]=="A" else [80,80,80]
        rows.append({"arm_id":item["arm_id"],"block":item["block"],"position":item["position"],
                     "lane_id":"L0","oracle_ok":True,
                     "samples_ns":custom.get(key,[fallback,fallback])[occurrence]})
    lane=statistics.analyze(rows,arms=["A","B"],baseline="A",lanes=[one_lane()],policy=policy(seed=7))["lanes"]["L0"]
    assert lane["arm_absolute"]["A"]["block_values"][0]==8
    assert lane["arm_absolute"]["B"]["block_values"][0]==1
    assert lane["arm_absolute"]["B"]["block_values"][1]==1.5
    assert lane["comparisons"]["B"]["retained_paired_ratios"][0]==.125


def test_host_context_rejects_unsupported_platform_cores_and_tools(tmp_path,monkeypatch):
    # I-14: every unsupported host property fails closed before acquisition.
    monkeypatch.setattr(runtime,"_core_ids",lambda:[(0,0,0),(1,0,1)])
    monkeypatch.setattr(runtime,"_filesystem",lambda root:"ext4")
    monkeypatch.setattr(runtime,"_tool",lambda argv:"tool 1.0")
    monkeypatch.setattr(runtime.shutil,"which",lambda name:"/usr/bin/taskset")
    uname=platform.uname()
    monkeypatch.setattr(runtime.platform,"uname",lambda:uname._replace(system="Darwin",release="23.0"))
    with pytest.raises(runtime.MeasurementBlocked,match="Linux or WSL2"):
        runtime.host_context(tmp_path,check=True)
    monkeypatch.setattr(runtime.platform,"uname",lambda:uname)
    monkeypatch.setattr(runtime,"_core_ids",lambda:[(0,0,0)])
    with pytest.raises(runtime.MeasurementBlocked,match="two distinct"):
        runtime.host_context(tmp_path,check=True)
    monkeypatch.setattr(runtime,"_core_ids",lambda:[(0,0,0),(1,0,1)])
    monkeypatch.setattr(runtime.shutil,"which",lambda name:None)
    with pytest.raises(runtime.MeasurementBlocked,match="taskset"):
        runtime.host_context(tmp_path,check=True)
    monkeypatch.setattr(runtime.shutil,"which",lambda name:"/usr/bin/taskset")
    monkeypatch.setattr(runtime,"_tool",lambda argv:"UNAVAILABLE" if argv[0]=="rustc" else "tool 1.0")
    with pytest.raises(runtime.MeasurementBlocked,match="Rust toolchain"):
        runtime.host_context(tmp_path,check=True)
    assert runtime.host_context(tmp_path,check=False)["filesystem"]=="ext4"


def test_host_readiness_and_affinity_pure_mocks(monkeypatch):
    counters=iter([(100,10,0),(200,20,0),(300,25,0),(400,30,0),(500,40,0)])
    monkeypatch.setattr(runtime,"_cpu_ticks",lambda cpu:next(counters))
    monkeypatch.setattr(runtime.time,"sleep",lambda seconds:None)
    report=runtime.assess_readiness(2)
    assert report["status"]=="clear"
    counters=iter([(100,10,0),(200,90,0),(300,150,0),(400,180,0),(500,220,0)])
    report=runtime.assess_readiness(2)
    assert report["status"]=="busy"
    current={1,2,3}
    def getter(pid): return set(current)
    def setter(pid,new): current.clear(); current.update(new)
    monkeypatch.setattr(runtime.os,"sched_getaffinity",getter)
    monkeypatch.setattr(runtime.os,"sched_setaffinity",setter)
    with runtime.pinned_controller(1):
        assert current=={1}
    assert current=={1,2,3}
    with pytest.raises(ZeroDivisionError):
        with runtime.pinned_controller(2):
            raise ZeroDivisionError()
    assert current=={1,2,3}


def test_programs_build_seams_without_compiler(monkeypatch,tmp_path):
    cfg=configuration.default_configuration("retained-key","r1","four strategies")
    monkeypatch.setattr(runtime,"_git",lambda *a:"f"*40)
    builds=[]
    def rust(root,target,*,engine,feature,source_root=None):
        builds.append((engine,feature,source_root is not None))
        return [f"mock-{len(builds)}"]
    monkeypatch.setattr(runtime,"_build_rust",rust)
    commands=[]
    monkeypatch.setattr(runtime,"_run",lambda argv,**kw:commands.append(argv) or None)
    q,context=runtime.build_programs(cfg,tmp_path,tmp_path/"scratch")
    assert set(q)=={"A","L","P","H"}
    assert q["L"]==q["P"]==q["H"]
    assert builds==[("quervant",True,False),("quervant",False,True)]
    assert context["quervant_strategy_feature_enabled"] is True
    assert len(commands)==2 and "--detach" in commands[0]
    cross=configuration.default_configuration("cross-engine","r2","three adapters")
    monkeypatch.setattr(runtime,"_build_lucene",lambda root,target:["mock-lucene"])
    builds.clear()
    q,context=runtime.build_programs(cross,tmp_path,tmp_path/"scratch")
    assert set(q)=={"Q","T","J"}
    assert builds==[("quervant",False,False),("tantivy",False,False)]
    assert context["quervant_strategy_feature_enabled"] is False
    assert "baseline_ref" not in context


def test_cli_prepare_validate_report_and_analyze(tmp_path,capsys,monkeypatch):
    configdir=tmp_path/"studies"
    assert cli.main(["prepare","--family","retained-key","--name","cli-study", "--description","CLI test",
                     "--studies-root",str(configdir)])==0
    path=list(configdir.rglob("*.json"))[0]
    assert path.parent.parent.name=="warm"
    assert cli.main(["validate","--config",str(path)])==0
    assert "VALID" in capsys.readouterr().out
    config=artifacts.load_configuration(path)
    config["policy"].update(blocks=4,samples=3,bootstrap_resamples=100)
    # Recreate configuration once before results reference it.
    path.unlink(); artifacts.create_configuration(path.parent,config)
    rows=sample_rows(arms=tuple(config["arms"]),blocks=4,values={"A":100,"L":90,"P":80,"H":120},seed=config["policy"]["seed"])
    result={**raw_result(config),"analysis":{},"configuration":config,
            "raw_samples":rows,"lanes":[one_lane()]}
    saved=artifacts.publish_result(path,path.parent.parent/"results",result)
    assert cli.main(["analyze","--result",str(saved)])==0
    assert '"gain_percent": 20.0' in capsys.readouterr().out
    assert cli.main(["report","--result",str(saved)])==0
    assert "INCOMPLETE" in capsys.readouterr().out


def test_host_context_native_and_rejected_filesystem(tmp_path,monkeypatch):
    monkeypatch.setattr(runtime,"_core_ids",lambda:[(2,0,2),(4,0,4)])
    monkeypatch.setattr(runtime,"_filesystem",lambda root:"ext4")
    monkeypatch.setattr(runtime,"_tool",lambda argv:"tool 1.0")
    monkeypatch.setattr(runtime.shutil,"which",lambda name:"/usr/bin/taskset")
    host=runtime.host_context(tmp_path,check=True)
    assert host["filesystem"]=="ext4" and host["physical_core_candidates"][1][0]==4
    monkeypatch.setattr(runtime,"_filesystem",lambda root:"overlay")
    with pytest.raises(runtime.MeasurementBlocked,match="native Linux filesystem"):
        runtime.host_context(tmp_path,check=True)
    host=runtime.host_context(tmp_path,check=False)
    assert host["filesystem"]=="overlay"


def test_cpu_topology_and_tick_reader_with_mocked_proc(monkeypatch):
    monkeypatch.setattr(runtime.os,"sched_getaffinity",lambda pid:{2,3})
    def get_text(self,*a,**k):
        if str(self).endswith("package_id"):return "0"
        if str(self).endswith("core_id"):return str(self).split("/topology/")[0].split("cpu")[-1]
        raise OSError("unexpected path")
    monkeypatch.setattr(runtime.Path,"read_text",get_text)
    assert runtime._core_ids()==[(2,0,2),(3,0,3)]
    import builtins,io
    original=builtins.open
    def open_fake(path,*a,**kw):
        if path=="/proc/stat":
            return io.StringIO("cpu 1 2 3 4 5 6 7 8\ncpu7 10 10 10 20 5 1 1 2\n")
        return original(path,*a,**kw)
    monkeypatch.setattr(builtins,"open",open_fake)
    assert runtime._cpu_ticks(7)==(59,34,2)
    with pytest.raises(runtime.MeasurementBlocked,match="observation missing"):
        runtime._cpu_ticks(9)


def test_subprocess_wrapper_and_toolchain(tmp_path):
    import sys
    result=runtime._run([sys.executable,"-c","print(123)"],timeout=3)
    assert result.stdout.strip()=="123"
    assert runtime._tool([sys.executable,"-c","print('v1')"])=="v1"
    with pytest.raises(runtime.MeasurementBlocked,match="exit 7"):
        runtime._run([sys.executable,"-c","raise SystemExit(7)"],timeout=3)
    with pytest.raises(runtime.MeasurementBlocked,match="subprocess failed"):
        runtime._run(["/program-not-present-anywhere"],timeout=3)


def test_build_rust_and_lucene_with_mocked_tools(tmp_path,monkeypatch):
    root=tmp_path/"root"
    for engine in ("quervant","tantivy"):
        manifest=root/"benchmarks"/"pr15d"/"adapters"/engine/"Cargo.toml"
        manifest.parent.mkdir(parents=True,exist_ok=True)
        manifest.write_text("[package]\n")
    lucene=root/"benchmarks"/"pr15d"/"adapters"/"lucene"
    lucene.mkdir()
    (lucene/"gradlew").write_text("#!/bin/sh\n")
    def fake_run(argv,**kw):
        if argv[0]=="cargo":
            target=Path(argv[argv.index("--target-dir")+1])/"release"/f"pr15d-{Path(argv[argv.index('--manifest-path')+1]).parent.name}-adapter"
        else:
            target=Path(kw["env"]["PR15D_LUCENE_BUILD_DIR"])/"install"/"pr15d-lucene-adapter"/"bin"/"pr15d-lucene-adapter"
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text("fake-binary")
        return None
    monkeypatch.setattr(runtime,"_run",fake_run)
    q=runtime._build_rust(root,tmp_path/"build1",engine="quervant",feature=True)
    t=runtime._build_rust(root,tmp_path/"build2",engine="tantivy",feature=False)
    l=runtime._build_lucene(root,tmp_path/"build3")
    assert all(Path(s[0]).exists() for s in (q,t,l))
    with pytest.raises(runtime.MeasurementBlocked):
        runtime._build_rust(root,tmp_path/"n",engine="unknown",feature=False)


def test_phase_feeds_complete_scheduled_slots(monkeypatch):
    cfg=configuration.default_configuration("retained-key","r1","Four arms")
    cfg["policy"].update(blocks=4, slots_per_arm=2)
    slots=[]
    def fake_slot(config,arm,lanes,command,indexes,*,block,position,cpu):
        return [{"block":block,"position":position,"arm_id":arm,"lane_id":"L0"}]
    monkeypatch.setattr(runtime,"collect_slot",fake_slot)
    result=runtime._phase(cfg,[one_lane()],{a:["mock"] for a in cfg["arms"]},
                          {a:{} for a in cfg["arms"]},cpu=None,on_slot=lambda chunk:slots.extend(chunk))
    assert len(result)==32 and len(slots)==32
    assert all(len([x for x in result if x["block"]==n])==8 for n in range(1,5))


def test_reporting_index_and_throughput_tables(tmp_path):
    path,cfg=make_config(tmp_path)
    r=raw_result(cfg)
    r["configuration_name"]=cfg["name"]
    r["configuration_file"]=path.name
    r["analysis"]={"lanes":{},"estimator":"paired","bootstrap_method":"bootstrap"}
    r["index_metrics"]={"A":{"10000":{"index_ns":1_000_000,"commit_ns":2_000_000,
                                             "reopen_ns":3_000_000,"index_bytes":128}}}
    r["throughput_metrics"]={"A":{"lane_id":"m","requests":100,"serial_ops_per_second":99.0,"status":"MEASURED"}}
    report=reporting.render_report(r)
    assert "## Indexing, commit and size" in report
    assert "## Serial throughput" in report
    assert "99" in report and "128" in report


def test_statistical_input_boundaries_and_result_status():
    rows=sample_rows()
    basic={"arms":["A","B"],"baseline":"A","lanes":[one_lane()],"policy":policy()}
    for invalid in (
        policy(seed=-1),policy(bootstrap_resamples=100001),policy(exclude_blocks={"other":[1]}),
        policy(exclude_blocks={"L0":[1,1]}),policy(exclude_blocks={"L0":[0]}),
        policy(min_blocks=0),policy(samples=0),
    ):
        with pytest.raises(artifacts.ArtifactError):
            statistics.analyze(rows,arms=basic["arms"],baseline="A",lanes=basic["lanes"],policy=invalid)
    assert runtime._run_status({"lanes":{}})=="INCONCLUSIVE"
    assert runtime._run_status({"lanes":{"one":{"comparisons":{"B":{"status":"REGRESSED"}}}}})=="COMPLETE"
    assert runtime._run_status({"lanes":{"one":{"comparisons":{"B":{"status":"NON_COMPARABLE"}}}}})=="INCONCLUSIVE"


def test_result_prevents_bad_source_file_data(tmp_path):
    path,cfg=make_config(tmp_path)
    r=raw_result(cfg)
    r["configuration_id"]="garbage"
    with pytest.raises(artifacts.ArtifactError):
        artifacts.publish_result(path,path.parent.parent/"results",r)
    fake=path.parent/("other-"+path.name)
    fake.write_text(path.read_text())
    with pytest.raises(artifacts.ArtifactError):
        artifacts.load_configuration(fake)
    assert not list((path.parent.parent/"results").glob("*.json")) if (path.parent.parent/"results").exists() else True
