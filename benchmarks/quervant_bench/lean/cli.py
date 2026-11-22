"""BM-10 CLI: two persisted artifacts, one automatic execution path.

`prepare` creates a configuration. `run` executes an actual benchmark, then saves
one result JSON (complete or incomplete). `analyze` reads stored samples and
recomputes statistics without timing. `report`/`replay` only render stored values.
No receipt, approval, seal, attestation, or evidence-admission verbs exist.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .artifacts import ArtifactError, load_configuration, load_result
from .configuration import prepare_configuration, validate_configuration
from .reporting import replay_to_markdown
from .runtime import run_benchmark
from .statistics import analyze, compare_historical


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quervant-bench", description="Direct Quervant benchmark configuration, execution and results")
    sub = p.add_subparsers(dest="action", required=True)
    make = sub.add_parser("prepare", help="save an immutable, dated benchmark configuration")
    make.add_argument("--family", choices=("retained-key", "cross-engine"), required=True)
    make.add_argument("--name", required=True)
    make.add_argument("--description", required=True)
    make.add_argument("--regime", choices=("warm", "process-cold"), default="warm",
                      help="cross-engine study type (retained-key supports warm only)")
    make.add_argument("--config-dir", type=Path, default=repo_root() / "benchmarks" / "configurations")
    run = sub.add_parser("run", help="run a configured REAL benchmark, automatically and without approvals")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--result-dir", type=Path, default=repo_root() / "benchmarks" / "results")
    run.add_argument("--scratch-root", type=Path, help="temporary build, corpus, and index files (default target/bm10)")
    validate = sub.add_parser("validate", help="validate a configuration's ordinary shape and semantics")
    validate.add_argument("--config", type=Path, required=True)
    analyze_cmd = sub.add_parser("analyze", help="recalculate analysis from saved raw samples, without timing or writing")
    analyze_cmd.add_argument("--result", type=Path, required=True)
    compare = sub.add_parser("compare", help="compare within-run gains from two saved result JSONs")
    compare.add_argument("--current", type=Path, required=True)
    compare.add_argument("--historical", type=Path, required=True)
    compare.add_argument("--lane", required=True)
    compare.add_argument("--arm", required=True)
    for name in ("report", "replay"):
        report = sub.add_parser(name, help="render stored result values as Markdown (no recalculation)")
        report.add_argument("--result", type=Path, required=True)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.action == "prepare":
            print(prepare_configuration(args.config_dir, family=args.family, name=args.name,
                                        description=args.description, regime=args.regime))
        elif args.action == "validate":
            validate_configuration(load_configuration(args.config))
            print("VALID")
        elif args.action == "run":
            location, result = run_benchmark(args.config, args.result_dir,
                                             root=repo_root(), scratch_root=args.scratch_root)
            print(f"RESULT_JSON={location}")
            print(replay_to_markdown(location))
            return 0 if result["status"] != "INCOMPLETE" else 4
        elif args.action == "analyze":
            result = load_result(args.result)
            config = result["configuration"]
            validate_configuration(config)
            analysis = analyze(result["raw_samples"], arms=list(config["arms"]),
                               baseline=config["baseline"], lanes=result["lanes"], policy=config["policy"])
            print(json.dumps(analysis, indent=2, sort_keys=True, allow_nan=False))
        elif args.action == "compare":
            comparison = compare_historical(load_result(args.current), load_result(args.historical),
                                            lane_id=args.lane, treatment_arm=args.arm)
            print(json.dumps(comparison, indent=2, sort_keys=True, allow_nan=False))
        elif args.action in ("report", "replay"):
            print(replay_to_markdown(args.result), end="")
        return 0
    except (ArtifactError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"BM10_ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
