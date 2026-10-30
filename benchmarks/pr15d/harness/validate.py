#!/usr/bin/env python3
"""Strict PR15D validator.

The validator never repairs data. It independently re-derives the oracle from
the frozen TSV bytes, recomputes every summary statistic, enforces the 3x20
sample contract and refuses to certify a partial, contended, mislabelled or
semantically different run.

Exit codes: 0 QUALIFIED, 2 INVALID, 3 UNQUALIFIED/BLOCKED.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "corpus"))

import oracle  # noqa: E402
import run  # noqa: E402

EXIT_QUALIFIED = 0
EXIT_INVALID = 2
EXIT_UNQUALIFIED = 3


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive(value) -> bool:
    return _is_int(value) and value > 0


def _load_json(path: str, label: str, errors: list):
    try:
        with open(path, "rb") as handle:
            return json.loads(handle.read().decode("utf-8"))
    except FileNotFoundError:
        errors.append({"code": "missing_file", "detail": f"{label}: {path}"})
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        errors.append({"code": "malformed_json", "detail": f"{label}: {error}"})
    return None


def _expected_lane_map(rows_by_n: dict) -> dict:
    lanes = {}
    for descriptor in run.lane_descriptors():
        result = oracle.expected(
            rows_by_n[descriptor["n"]],
            descriptor["field"],
            descriptor["term"],
            descriptor["k"],
        )
        lanes[run.lane_key(descriptor)] = {
            **descriptor,
            "expected_total_hits": result["total_hits"],
            "expected_doc_ids": result["doc_ids"],
        }
    return lanes


def _check_build(engine: str, trial: int, manifest: dict, errors: list) -> None:
    build = manifest.get("build")
    if not isinstance(build, dict):
        errors.append(
            {"code": "build_failed", "detail": f"{engine} trial {trial}: build section missing"}
        )
        return
    for n in run.N_VALUES:
        entry = build.get(str(n))
        if not isinstance(entry, dict):
            errors.append(
                {"code": "build_failed", "detail": f"{engine} trial {trial} N={n}"}
            )
            continue
        if entry.get("documents_indexed") != n:
            errors.append(
                {
                    "code": "wrong_document_count",
                    "detail": f"{engine} trial {trial} N={n}: indexed {entry.get('documents_indexed')}",
                }
            )
        if entry.get("documents_verified") != n:
            errors.append(
                {
                    "code": "commit_or_reopen_failed",
                    "detail": f"{engine} trial {trial} N={n}: verified {entry.get('documents_verified')}",
                }
            )
        for field in ("index_ns", "commit_ns", "reopen_ns", "index_bytes"):
            if not _positive(entry.get(field)):
                errors.append(
                    {
                        "code": "nonpositive_duration" if field != "index_bytes" else "index_bytes_invalid",
                        "detail": f"{engine} trial {trial} N={n}: {field}={entry.get(field)!r}",
                    }
                )
        segments = entry.get("segment_count")
        if not _positive(segments):
            errors.append(
                {
                    "code": "segment_count_invalid",
                    "detail": f"{engine} trial {trial} N={n}: {segments!r}",
                }
            )


def validate_trial(
    manifest,
    *,
    engine: str,
    trial: int,
    run_record: dict,
    lane_map: dict,
    errors: list,
    unqualified: list,
) -> None:
    if not isinstance(manifest, dict):
        errors.append({"code": "malformed_json", "detail": f"{engine} trial {trial}"})
        return
    if manifest.get("schema") != run.SCHEMA_TRIAL:
        errors.append(
            {
                "code": "schema_mismatch",
                "detail": f"{engine} trial {trial}: {manifest.get('schema')!r}",
            }
        )
    if manifest.get("engine") != engine:
        errors.append(
            {"code": "missing_engine", "detail": f"trial {trial}: file says {manifest.get('engine')!r}"}
        )
    if manifest.get("trial") != trial:
        errors.append(
            {"code": "missing_trial", "detail": f"{engine}: file says trial {manifest.get('trial')!r}"}
        )
    if manifest.get("source_sha") != run_record.get("source_sha"):
        errors.append(
            {
                "code": "source_sha_mismatch",
                "detail": f"{engine} trial {trial}",
            }
        )
    if manifest.get("release_build") is not True:
        errors.append({"code": "release_build_false", "detail": f"{engine} trial {trial}"})
    if manifest.get("native_filesystem") is not True:
        unqualified.append({"code": "native_filesystem_unavailable", "detail": engine})
    if manifest.get("filesystem") != run_record.get("filesystem"):
        unqualified.append({"code": "non_native_filesystem", "detail": engine})
    if manifest.get("operator_idle_attested") is not True:
        unqualified.append({"code": "idle_attestation_missing", "detail": engine})
    if not manifest.get("engine_version"):
        errors.append({"code": "engine_version_missing", "detail": f"{engine} trial {trial}"})
    if manifest.get("host_fingerprint") != run_record.get("host_fingerprint"):
        errors.append({"code": "mixed_host", "detail": f"{engine} trial {trial}"})
    if manifest.get("corpus_digests") != run_record.get("corpus_digests"):
        errors.append({"code": "corpus_digest_mismatch", "detail": f"{engine} trial {trial}"})
    if manifest.get("corpus_manifest_sha256") != run_record.get("corpus_manifest_sha256"):
        errors.append(
            {"code": "corpus_digest_mismatch", "detail": f"{engine} trial {trial} manifest SHA"}
        )
    expected_analyzer_map = {"doc_id": run.ANALYZER, "key": run.ANALYZER, "group": run.ANALYZER}
    if manifest.get("analyzer_map") != expected_analyzer_map:
        errors.append(
            {"code": "analyzer_map_mismatch", "detail": f"{engine} trial {trial}"}
        )

    _check_build(engine, trial, manifest, errors)

    lanes = manifest.get("lanes")
    if not isinstance(lanes, list):
        errors.append({"code": "missing_lane", "detail": f"{engine} trial {trial}"})
        lanes = []
    seen = set()
    for lane in lanes:
        if not isinstance(lane, dict):
            errors.append({"code": "malformed_json", "detail": f"{engine} trial {trial} lane"})
            continue
        key = (
            lane.get("n"),
            lane.get("class"),
            lane.get("k"),
            lane.get("regime"),
        )
        if key in seen:
            errors.append({"code": "duplicate_lane", "detail": f"{engine} trial {trial}: {key}"})
            continue
        seen.add(key)
        regime = lane.get("regime")
        if regime not in run.REGIMES:
            errors.append(
                {
                    "code": "wrong_regime_label",
                    "detail": f"{engine} trial {trial}: {regime!r} is not process_cold/warm",
                }
            )
        descriptor = lane_map.get(key)
        if descriptor is None:
            errors.append(
                {"code": "unexpected_lane", "detail": f"{engine} trial {trial}: {key}"}
            )
            continue
        if lane.get("id") != descriptor["id"]:
            errors.append({"code": "lane_id_mismatch", "detail": f"{engine}: {key}"})
        if lane.get("field") != descriptor["field"] or lane.get("term") != descriptor["term"]:
            errors.append({"code": "lane_descriptor_mismatch", "detail": f"{engine}: {key}"})
        expected_warmups = run.WARMUPS if regime == "warm" else 0
        if lane.get("warmups") != expected_warmups:
            errors.append(
                {
                    "code": "warmup_accounting",
                    "detail": f"{engine} trial {trial} {key}: warmups={lane.get('warmups')!r}",
                }
            )
        samples = lane.get("samples_ns")
        if not isinstance(samples, list):
            errors.append({"code": "sample_count", "detail": f"{engine} trial {trial} {key}"})
            samples = []
        if len(samples) != run.MEASURED:
            errors.append(
                {
                    "code": "sample_count",
                    "detail": f"{engine} trial {trial} {key}: {len(samples)} != {run.MEASURED}",
                }
            )
        for sample in samples:
            if not _positive(sample):
                errors.append(
                    {
                        "code": "nonpositive_duration",
                        "detail": f"{engine} trial {trial} {key}: {sample!r}",
                    }
                )
        try:
            recomputed = run.summarize(samples)
        except ValueError as error:
            errors.append(
                {"code": "summary_invalid", "detail": f"{engine} trial {trial} {key}: {error}"}
            )
            recomputed = None
        if recomputed is not None and lane.get("summary_ns") != recomputed:
            errors.append(
                {"code": "summary_mismatch", "detail": f"{engine} trial {trial} {key}"}
            )
        if lane.get("oracle_ok") is not True:
            errors.append(
                {"code": "oracle_assertion_missing", "detail": f"{engine} trial {trial} {key}"}
            )
        total_hits = lane.get("total_hits")
        doc_ids = lane.get("doc_ids")
        if total_hits != descriptor["expected_total_hits"]:
            errors.append(
                {
                    "code": "oracle_mismatch",
                    "detail": f"{engine} trial {trial} {key}: total {total_hits} != {descriptor['expected_total_hits']}",
                }
            )
        if not isinstance(doc_ids, list) or doc_ids != descriptor["expected_doc_ids"]:
            errors.append(
                {"code": "oracle_mismatch", "detail": f"{engine} trial {trial} {key}: doc_ids"}
            )
            doc_ids = doc_ids if isinstance(doc_ids, list) else []
        if lane.get("expected_total_hits") != descriptor["expected_total_hits"]:
            errors.append({"code": "oracle_mismatch", "detail": f"{engine} trial {trial} {key}"})
        if lane.get("expected_doc_ids") != descriptor["expected_doc_ids"]:
            errors.append({"code": "oracle_mismatch", "detail": f"{engine} trial {trial} {key}"})
        if any(doc_ids[index - 1] >= doc_ids[index] for index in range(1, len(doc_ids))):
            errors.append(
                {"code": "ordering", "detail": f"{engine} trial {trial} {key}"}
            )
        if len(doc_ids) != min(descriptor["k"], descriptor["expected_total_hits"]):
            errors.append(
                {"code": "hit_count", "detail": f"{engine} trial {trial} {key}: {len(doc_ids)}"}
            )
        if lane.get("analyzer") != run.ANALYZER:
            errors.append(
                {"code": "analyzer_map_mismatch", "detail": f"{engine} trial {trial} {key}"}
            )
        contention = lane.get("contention")
        if not isinstance(contention, dict):
            unqualified.append(
                {"code": "contention_not_clear", "detail": f"{engine} trial {trial} {key}"}
            )
        else:
            for phase in ("pre", "post"):
                if contention.get(phase) != "clear":
                    unqualified.append(
                        {
                            "code": "contention_not_clear",
                            "detail": f"{engine} trial {trial} {key}: {phase}={contention.get(phase)!r}",
                        }
                    )

    expected_keys = set(lane_map)
    if seen != expected_keys:
        missing = sorted(expected_keys - seen)
        if missing:
            errors.append(
                {"code": "missing_lane", "detail": f"{engine} trial {trial}: {missing}"}
            )

    _check_throughput(engine, trial, manifest, errors)


def _check_throughput(engine: str, trial: int, manifest: dict, errors: list) -> None:
    entries = manifest.get("throughput")
    if not isinstance(entries, list):
        errors.append({"code": "throughput_invalid", "detail": f"{engine} trial {trial}"})
        return
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append({"code": "throughput_invalid", "detail": f"{engine} trial {trial}"})
            continue
        n = entry.get("n")
        if n in seen:
            errors.append({"code": "throughput_invalid", "detail": f"{engine} duplicate N={n}"})
        seen.add(n)
        if entry.get("requests") != run.THROUGHPUT_REQUESTS:
            errors.append({"code": "throughput_invalid", "detail": f"{engine} N={n} requests"})
        wall_ns = entry.get("wall_ns")
        if not _positive(wall_ns):
            errors.append({"code": "throughput_invalid", "detail": f"{engine} N={n} wall_ns"})
            continue
        expected_rate = round(run.THROUGHPUT_REQUESTS * 1_000_000_000 / wall_ns, 6)
        if entry.get("serial_ops_per_second") != expected_rate:
            errors.append({"code": "throughput_invalid", "detail": f"{engine} N={n} rate"})
    if seen != set(run.N_VALUES):
        errors.append(
            {"code": "throughput_invalid", "detail": f"{engine} trial {trial}: N set {sorted(seen)}"}
        )


def _check_trial_series(loaded: dict, errors: list) -> None:
    for engine, trials in loaded.items():
        if set(trials) != set(range(1, run.REQUIRED_TRIALS + 1)):
            if len(trials) == run.REQUIRED_TRIALS:
                errors.append(
                    {
                        "code": "missing_trial",
                        "detail": f"{engine}: trial ids {sorted(trials)}",
                    }
                )
        if len(trials) != run.REQUIRED_TRIALS:
            errors.append(
                {
                    "code": "trial_count_below_minimum",
                    "detail": f"{engine}: {len(trials)} qualified trial manifests",
                }
            )
            continue
        first = trials[1]
        codes = {
            "engine_version": "engine_version_mismatch",
            "source_sha": "source_sha_mismatch",
            "host_fingerprint": "mixed_host",
            "analyzer_map": "analyzer_map_mismatch",
        }
        for field, code in codes.items():
            value = first.get(field)
            for trial, manifest in trials.items():
                if manifest.get(field) != value:
                    errors.append(
                        {"code": code, "detail": f"{engine} trial {trial}: {field}"}
                    )
        for n in run.N_VALUES:
            sizes = {}
            for trial, manifest in trials.items():
                build = manifest.get("build")
                if not isinstance(build, dict) or not isinstance(build.get(str(n)), dict):
                    continue
                sizes[trial] = build[str(n)].get("index_bytes")
            if len(sizes) == len(trials) and len(set(sizes.values())) != 1:
                errors.append(
                    {
                        "code": "index_bytes_inconsistent",
                        "detail": f"{engine} N={n}: {sizes}",
                    }
                )


def validate_run(run_dir: str) -> dict:
    errors: list = []
    unqualified: list = []
    report = {
        "schema": run.SCHEMA_VALIDATION,
        "run_id": os.path.basename(os.path.abspath(run_dir)),
        "status": "INVALID",
        "errors": errors,
        "unqualified": unqualified,
    }
    run_record = _load_json(os.path.join(run_dir, "run.json"), "run.json", errors)
    if run_record is None:
        return report
    if run_record.get("schema") != run.SCHEMA_RUN:
        errors.append({"code": "schema_mismatch", "detail": "run.json"})
    report["source_sha"] = run_record.get("source_sha")
    if run_record.get("status") == "blocked":
        report["status"] = "BLOCKED"
        report["blockers"] = run_record.get("blockers", [])
        return report
    if run_record.get("status") != "complete":
        errors.append(
            {
                "code": "partial_unlabeled",
                "detail": f"run status {run_record.get('status')!r} is not 'complete'",
            }
        )
    if run_record.get("idle_attested") is not True:
        unqualified.append({"code": "idle_attestation_missing", "detail": "run.json"})
    if run_record.get("native_filesystem") is not True:
        unqualified.append({"code": "native_filesystem_unavailable", "detail": "run.json"})
    if run_record.get("trials") != run.REQUIRED_TRIALS:
        errors.append({"code": "trial_count_below_minimum", "detail": "run.json trials"})
    if not run_record.get("source_sha"):
        errors.append({"code": "clean_tree_missing", "detail": "run.json source_sha"})

    corpus_dir = run_record.get("corpus_dir")
    rows_by_n = None
    if not corpus_dir:
        errors.append({"code": "corpus_digest_mismatch", "detail": "run.json corpus_dir missing"})
    else:
        try:
            manifest, rows_by_n = oracle.load_and_verify(corpus_dir)
        except oracle.CorpusError as error:
            errors.append({"code": error.code, "detail": error.detail})
            rows_by_n = None
        else:
            manifest_sha = oracle.sha256_bytes(oracle.canonical_json_bytes(manifest))
            if run_record.get("corpus_manifest_sha256") != manifest_sha:
                errors.append(
                    {"code": "corpus_digest_mismatch", "detail": "manifest SHA differs"}
                )
            recorded = {
                str(entry["n"]): entry["sha256"] for entry in manifest["corpora"]
            }
            if run_record.get("corpus_digests") != recorded:
                errors.append(
                    {"code": "corpus_digest_mismatch", "detail": "TSV digest differs"}
                )

    trials_root = os.path.join(run_dir, "trials")
    loaded: dict = {engine: {} for engine in run.ENGINES}
    if rows_by_n is not None:
        lane_map = _expected_lane_map(rows_by_n)
        for trial in range(1, run.REQUIRED_TRIALS + 1):
            for engine in run.ENGINES:
                path = os.path.join(trials_root, f"trial-{trial}", f"{engine}.json")
                if not os.path.isfile(path):
                    errors.append(
                        {"code": "missing_trial", "detail": f"{engine} trial {trial}"}
                    )
                    continue
                manifest = _load_json(path, f"{engine} trial {trial}", errors)
                if manifest is None:
                    continue
                loaded[engine][trial] = manifest
                validate_trial(
                    manifest,
                    engine=engine,
                    trial=trial,
                    run_record=run_record,
                    lane_map=lane_map,
                    errors=errors,
                    unqualified=unqualified,
                )
        # Reject extra trial files that would otherwise be silently ignored.
        if os.path.isdir(trials_root):
            for directory in sorted(os.listdir(trials_root)):
                full = os.path.join(trials_root, directory)
                if not os.path.isdir(full):
                    errors.append(
                        {"code": "unexpected_artifact", "detail": directory}
                    )
                    continue
                for name in sorted(os.listdir(full)):
                    if name not in {f"{engine}.json" for engine in run.ENGINES}:
                        errors.append(
                            {"code": "unexpected_artifact", "detail": f"{directory}/{name}"}
                        )
        _check_trial_series(loaded, errors)

    scored = run_record.get("scored_lane")
    if scored is not None:
        status = scored.get("status")
        if status != "SEMANTICALLY_NONCOMPARABLE":
            if not scored.get("semantic_proof"):
                errors.append(
                    {"code": "scored_lane_invalid", "detail": "no cross-engine score proof"}
                )

    if errors:
        report["status"] = "INVALID"
        return report
    if unqualified or not run_record.get("qualified", False):
        report["status"] = "UNQUALIFIED"
        return report
    report["status"] = "QUALIFIED"
    report["engines"] = list(run.ENGINES)
    report["trials"] = run.REQUIRED_TRIALS
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Strictly validate a PR15D run.")
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    report = validate_run(args.run)
    run.write_json(args.out, report)
    print(json.dumps({"status": report["status"], "errors": len(report["errors"])}))
    if report["status"] == "QUALIFIED":
        return EXIT_QUALIFIED
    if report["status"] == "INVALID":
        return EXIT_INVALID
    return EXIT_UNQUALIFIED


if __name__ == "__main__":
    raise SystemExit(main())
