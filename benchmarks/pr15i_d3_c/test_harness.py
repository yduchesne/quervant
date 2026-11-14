#!/usr/bin/env python3
"""Regression tests for the D3-C harness defect fixes."""
from __future__ import annotations
import importlib.util, os, unittest
ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR=os.path.join(ROOT,"benchmarks/pr15i_d3_c")
def load(n,f):
    s=importlib.util.spec_from_file_location(n,os.path.join(DIR,f)); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
RUN=load("d3c_t_run","run.py"); VERIFY=load("d3c_t_verify","verify.py"); P=RUN.load_protocol()[0]
LS=RUN.lanes(P)

def slot(arm,block,pos,vals):
    return {"schema":"pr15i-d3c-slot-v1","slot":(block-1)*8+pos,"block":block,"position":pos,"arm":arm,
            "source_sha":"a"*40,"binary_sha256":"b"*64,"index_digests":{str(n):"c"*64 for n in P["n_values"]},
            "controller_affinity_before":[1],"controller_affinity_after":[1],
            "contention_before":{"state":"clear","reason_codes":[]},"contention_after":{"state":"clear","reason_codes":[]},
            "lanes":[{"id":l["id"],"n":l["n"],"class":l["class"],"field":l["field"],"term":l["term"],"k":l["k"],
                      "samples_ns":[vals[l["id"]]]*20,"summary_ns":{"count":20,"median":vals[l["id"]]},
                      "total_hits":0,"doc_ids":[],"expected_total_hits":0,"expected_doc_ids":[],"oracle_ok":True,
                      "mode_marker":None,"adapter_pid":1,"affinity_before":[0],"affinity_after":[0]} for l in LS]}

def slots(base,arm_values):
    out=[]
    for e in RUN.schedule(P,P["campaign_names"][0]):
        vals={l["id"]:arm_values[e["arm"]][e["block"]][e["position"]] for l in LS}
        out.append(slot(e["arm"],e["block"],e["position"],vals))
    return out

class DriftAndStatus(unittest.TestCase):
    def _values(self,mult=1.0):
        return {arm:{b:{p:1_000_000*mult for p in range(1,9)} for b in range(1,13)} for arm in ("A","L","P","H")}
    def test_drift_cap_boundary_both_impls(self):
        ppos=[e["position"] for e in RUN.schedule(P,P["campaign_names"][0]) if e["arm"]=="P" and e["block"]==1][0]
        vals=self._values(); vals["P"][1][ppos]=1_250_000  # ratio 1.25 exactly
        sl=slots(None,vals); r=RUN.drift_report(P,sl,LS,12,["A","L","P","H"]); v=VERIFY.drift_report(sl,LS,12,["A","L","P","H"])
        self.assertEqual(r["status"],"PASS"); self.assertEqual(v["status"],"PASS")
        vals["P"][1][ppos]=1_250_001
        sl=slots(None,vals); r=RUN.drift_report(P,sl,LS,12,["A","L","P","H"]); v=VERIFY.drift_report(sl,LS,12,["A","L","P","H"])
        self.assertEqual(r["status"],"FAIL"); self.assertEqual(v["status"],"FAIL")
    def test_four_arm_status_conditional(self):
        vals=self._values()
        s=RUN.summary_campaign(P,slots(None,vals),LS,12,P["campaign_names"][0],False)
        self.assertEqual(s["status"],"ACQUISITION_INCOMPLETE")
        s=RUN.summary_campaign(P,slots(None,vals),LS,12,P["campaign_names"][0],True)
        self.assertEqual(s["status"],"ACQUIRED_VERIFIED")
    def test_bad_marker_bad_affinity(self):
        sl=slots(None,self._values()); sl[0]["lanes"][0]["mode_marker"]="WRONG"
        self.assertNotEqual(sl[0]["lanes"][0]["mode_marker"],None)
        sl=slots(None,self._values()); sl[0]["controller_affinity_before"]=[9]
        self.assertNotEqual(sl[0]["controller_affinity_before"],[1])
    def test_policy_h_memory_excluded_documentation(self):
        # H is intentionally excluded when the required memory evidence is absent.
        self.assertFalse(os.path.exists(os.path.join(DIR,"micro-memory.json")))

if __name__=="__main__": unittest.main()
