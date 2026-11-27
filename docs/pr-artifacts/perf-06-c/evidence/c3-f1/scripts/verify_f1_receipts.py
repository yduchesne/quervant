#!/usr/bin/env python3
"""Validate frozen receipt contracts; never execute recorded commands.

Usage: python3 verify_f1_receipts.py SPEC.json RECEIPTS_ROOT OUTPUT.json
SPEC and new OUTPUT must be outside RECEIPTS_ROOT. Diagnostics belong elsewhere.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
from decimal import Decimal
CURRENT = "contract"

def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def keys(value, allowed, required):
    require(isinstance(value, dict), "expected JSON object")
    require(set(value) <= set(allowed) and set(required) <= set(value), "unknown/missing keys")


def summaries(text):
    rows = re.findall(r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; \d+ measured; (\d+) filtered out;.*$", text, re.M)
    return [dict(status=s, passed=int(p), failed=int(f), ignored=int(i), filtered=int(z)) for s, p, f, i, z in rows]


def summary_equal(row, expected):
    keys(expected, ("passed", "failed", "ignored"), ("passed", "failed", "ignored"))
    require(all(type(v) is int and v >= 0 for v in expected.values()), "invalid expected totals")
    require({k: row[k] for k in expected} == expected, "test summary mismatch")
    require(row["status"] == ("FAILED" if expected["failed"] else "ok"), "test status mismatch")


def coverage(text):
    headers = re.findall(r"^Filename\s+.*$", text, re.M)
    totals = re.findall(r"^TOTAL\s+.*$", text, re.M)
    require(len(headers) == len(totals) == 1, "need exactly one coverage header and TOTAL")
    pattern = r"Filename|Missed Regions|Missed Functions|Missed Lines|Missed Branches|Regions|Functions|Executed|Lines|Branches|Cover"
    matches = list(re.finditer(pattern, headers[0]))
    require(not re.sub(pattern, "", headers[0]).strip(), "unknown coverage header")
    labels = [m.group() for m in matches]
    require(labels[0] == "Filename", "unknown coverage leading column")
    groups = [labels[i:i + 3] for i in range(1, len(labels), 3)]
    known = [["Regions", "Missed Regions", "Cover"], ["Functions", "Missed Functions", "Executed"],
             ["Lines", "Missed Lines", "Cover"], ["Branches", "Missed Branches", "Cover"]]
    require(len(groups) == 4 and sorted(groups) == sorted(known), "unsupported coverage columns")
    cells = totals[0].split()
    require(len(cells) == len(labels) and cells[0] == "TOTAL", "coverage column count mismatch")
    result = {}
    for label in ("Regions", "Functions", "Lines", "Branches"):
        index = labels.index(label)
        require(cells[index].isdigit() and cells[index + 1].isdigit(), "invalid coverage counts")
        total, missed = int(cells[index]), int(cells[index + 1])
        require(0 <= missed <= total, "invalid missed count")
        value = cells[index + 2]
        if total == 0:
            require(value == "-", "unexpected zero-total percentage")
        else:
            require(re.fullmatch(r"\d{1,3}\.\d{2}%", value), "unknown percentage format")
            actual = Decimal(100) * (total - missed) / total
            require(abs(Decimal(value[:-1]) - actual) <= Decimal("0.005"), "coverage arithmetic mismatch")
        result[label.lower()] = dict(total=total, missed=missed, covered=total - missed, percent=value)
    require(result["lines"]["total"] > 0, "empty line coverage")
    require(100 * result["lines"]["covered"] >= 85 * result["lines"]["total"], "line coverage below 85%")
    return result


def check_output(text, check, argv):
    kind = check.get("kind")
    fields = {"plain": ["empty"], "exact": ["name", "expected"], "summary": ["expected"],
              "inventory": ["names"], "workspace": ["targets", "expected", "bench_smoke", "expected_children"], "coverage": ["expected_lines"]}
    require(kind in fields, "unknown output check kind")
    keys(check, ["kind", "required_text", "forbidden_text"] + fields[kind], ["kind"])
    for needle in check.get("required_text", []):
        require(isinstance(needle, str) and needle in text, "required output text missing")
    for needle in check.get("forbidden_text", []):
        require(isinstance(needle, str) and needle not in text, "forbidden output text present")
    if kind == "plain":
        require(not check.get("empty", False) or text == "", "expected empty output")
        return {"kind": kind}
    if kind == "coverage":
        result = coverage(text)
        if "expected_lines" in check:
            require(result["lines"] == check["expected_lines"], "historical line coverage mismatch")
        return result
    if kind == "inventory":
        names = re.findall(r"^([^\r\n]+): test$", text, re.M)
        expected = check["names"]
        require(isinstance(expected, list) and all(isinstance(n, str) for n in expected), "invalid inventory contract")
        require(len(names) == len(set(names)) and len(expected) == len(set(expected)), "duplicate inventory name")
        require(sorted(names) == sorted(expected) and len(names) > 0, "inventory name-set mismatch")
        return {"count": len(names), "names": sorted(names)}
    if kind == "workspace":
        launches = list(re.finditer(r"^\s+Running ([^\r\n]+)$", text, re.M))
        require(not re.search(r"^\s*Doc-tests\b", text, re.M), "unexpected doctest scope")
        require(len(launches) == check["targets"], "workspace target count mismatch")
        require(not summaries(text[:launches[0].start()]), "summary outside Cargo target")
        result, children, benches, ambiguous = [], [], {}, False
        for i, launch in enumerate(launches):
            end = launches[i + 1].start() if i + 1 < len(launches) else len(text)
            block = text[launch.end():end]
            rows = summaries(block)
            announced = re.findall(r"^running (\d+) tests?$", block, re.M)
            target = launch.group(1).split(" (")[0]
            if target.startswith("benches/"):
                pairs = len(re.findall(r"^Testing .+$", block, re.M))
                require(not rows and not announced and pairs > 0 and pairs == len(re.findall(r"^Success$", block, re.M)), "unknown benchmark test-mode output")
                require(target not in benches, "duplicate benchmark target")
                benches[target] = pairs
                continue
            require(rows and announced and rows[-1]["filtered"] == 0, "missing/ambiguous parent summary")
            require(sum(rows[-1][k] for k in ("passed", "failed", "ignored")) == int(announced[0]), "parent target count mismatch")
            require(all(r["status"] == "ok" and r["failed"] == 0 for r in rows), "failed workspace test")
            require(all(r["filtered"] > 0 for r in rows[:-1]), "unknown child summary scope")
            ambiguous |= len(rows) != len(announced) or len(rows) != block.count("test result:")
            children.extend(rows[:-1])
            result.append(dict(target=launch.group(1), **rows[-1]))
        total = {k: sum(r[k] for r in result) for k in ("passed", "failed", "ignored")}
        child_total = {k: sum(r[k] for r in children) for k in ("passed", "failed", "ignored")}
        summary_equal(dict(status="ok", **total), check["expected"])
        require(benches == check["bench_smoke"], "benchmark test-mode target/count mismatch")
        if "expected_children" in check:
            require(not ambiguous, "historical child output unexpectedly ambiguous")
            summary_equal(dict(status="ok", **child_total), check["expected_children"])
        return dict(scope="parent libtest targets; child observations and benchmark test-mode results separate; no doctests",
                    targets=result, totals=total, child_summaries=children, observed_child_totals=child_total,
                    child_output_ambiguous=ambiguous, bench_test_mode=benches)
    rows = summaries(text)
    require(len(rows) == 1, "expected one test result summary")
    summary_equal(rows[0], check["expected"])
    if kind == "exact":
        name = check["name"]
        require("--exact" in argv and name in argv, "exact test argv mismatch")
        require(re.search(r"^running 1 test$", text, re.M), "exact test did not select one")
        require(re.search(r"^test " + re.escape(name) + r" \.\.\.", text, re.M), "exact test name absent")
    return rows[0]


def verify(spec_path, root):
    global CURRENT
    spec_bytes = spec_path.read_bytes()
    spec = json.loads(spec_bytes)
    keys(spec, ("schema", "receipts"), ("schema", "receipts"))
    require(spec["schema"] == "quervant-perf06-c3-f1-receipt-contract-v1", "unknown contract schema")
    require(isinstance(spec["receipts"], list) and spec["receipts"], "empty receipt contract")
    planned, labels, results = set(), set(), []
    for item in spec["receipts"]:
        CURRENT = item.get("label", "invalid contract row") if isinstance(item, dict) else "invalid contract row"
        keys(item, ("path", "label", "argv", "commit", "classification", "check"), ("path", "label", "argv", "commit", "classification", "check"))
        require(isinstance(item["argv"], list) and item["argv"] and all(isinstance(a, str) for a in item["argv"]), "invalid argv contract")
        path = root / item["path"]
        require(not Path(item["path"]).is_absolute() and ".." not in Path(item["path"]).parts, "unsafe receipt path")
        require(path.is_file() and not path.is_symlink() and root in path.resolve().parents, "missing/unsafe receipt")
        require(item["path"] not in planned and item["label"] not in labels, "duplicate contract path/label")
        planned.add(item["path"]); labels.add(item["label"])
        receipt_bytes = path.read_bytes()
        receipt = json.loads(receipt_bytes)
        require(receipt["schema"] == "quervant-perf06-c3-receipt-v1", "unknown recorder schema")
        require(receipt["label"] == item["label"] and receipt["argv"] == item["argv"], "receipt command/label mismatch")
        require(re.fullmatch(r"[0-9a-f]{40}", item["commit"]), "expected immutable commit")
        require(receipt["expected_commit"] == item["commit"], "receipt commit mismatch")
        before, after = receipt["before"], receipt["after"]
        require(receipt["source_identity_valid"] is True and before == after, "source identity changed")
        require(before["head"] == item["commit"] and before["tracked_status_b64"] == "", "unclean/wrong source")
        require(re.fullmatch(r"[0-9a-f]{40}", before["tree"]) and before["tree"] == before["index_tree"], "index/tree mismatch")
        require(receipt["removed_env_names"] == ["QUERVANT_PR15I_D3C_STRATEGY", "QUERVANT_PR15I_D3C_PREFILTER_PROFILE"], "environment removal mismatch")
        require(item["classification"] in ("BASELINE", "PASS", "EXPECTED_RED"), "unknown classification")
        expected_exit = 101 if item["classification"] == "EXPECTED_RED" else 0
        require(receipt["command_exit_code"] == expected_exit, "unexpected command exit")
        raw = base64.b64decode(receipt["combined_output_base64"], validate=True)
        require(len(raw) == receipt["combined_output_size"] and sha(raw) == receipt["combined_output_sha256"], "raw output hash/length mismatch")
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw.decode("utf-8"))
        checked = check_output(text, item["check"], item["argv"])
        results.append(dict(label=item["label"], path=item["path"], argv=item["argv"], commit=item["commit"],
                            classification=item["classification"], receipt_sha256=sha(receipt_bytes),
                            output_sha256=sha(raw), output_size=len(raw), check=checked))
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    require(actual == planned, "missing/undeclared acceptance files; keep diagnostics in sibling directory")
    return dict(status="PASS", schema="quervant-perf06-c3-f1-verification-v1", contract_sha256=sha(spec_bytes),
                verifier_sha256=sha(Path(__file__).read_bytes()), receipt_count=len(results), receipts=results)


if __name__ == "__main__":
    require(len(sys.argv) == 4, "usage: SPEC.json RECEIPTS_ROOT OUTPUT.json")
    spec_path, root, output = [Path(p).resolve() for p in sys.argv[1:]]
    require(root.is_dir() and root not in spec_path.parents and root not in output.parents, "spec/output must be outside receipt root")
    require(not output.exists(), "output must be a new file")
    try:
        result = verify(spec_path, root)
    except (ValueError, KeyError, TypeError, OSError) as error:
        result = dict(status="FAIL", context=CURRENT, error=str(error))
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "receipts"}, sort_keys=True))
    sys.exit(0 if result["status"] == "PASS" else 1)
