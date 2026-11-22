"""Presentation-only rendering of a saved BM-10 result. No analysis imports."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .artifacts import ArtifactError, load_result


def _cell(value: Any) -> str:
    """Render a literal Markdown table cell without allowing malformed tables."""
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.5g}"
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_report(result: Mapping[str, Any]) -> str:
    """Format precomputed values ONLY, including statuses and noncomparable lanes."""
    analysis = result.get("analysis")
    if not isinstance(analysis, dict):
        raise ArtifactError("saved result lacks an analysis object")
    if not isinstance(analysis.get("lanes"), dict):
        # An incomplete run is still a useful result JSON. Presentation of its
        # diagnostics and captured samples must never imply accepted timings.
        if result.get("status") != "INCOMPLETE":
            raise ArtifactError("complete result lacks finalized analysis")
        return "\n".join([
            f"# Incomplete benchmark: {_cell(result.get('configuration_name'))}", "",
            f"- Run ID: `{_cell(result.get('run_id'))}`",
            f"- Status: **INCOMPLETE**",
            f"- Raw slot/lane observations captured: {_cell(len(result.get('raw_samples', [])))}",
            f"- Errors: {_cell(result.get('errors', []))}",
            "", "This is incomplete evidence, not a performance comparison.", "",
        ])
    title = _cell(result.get("configuration_name", "Benchmark"))
    lines = [
        f"# Benchmark results: {title}", "",
        f"- Run ID: `{_cell(result.get('run_id'))}`",
        f"- Configuration: `{_cell(result.get('configuration_file'))}` (`{_cell(result.get('configuration_id'))}`)",
        f"- Executed (UTC): {_cell(result.get('executed_utc'))}",
        f"- Family: {_cell(result.get('family'))}",
        f"- Overall status: **{_cell(result.get('status'))}**", "",
        "Results show within-run treatment/baseline ratios (B/A). Positive gain means improvement.",
        "Separate runs must be compared using the change in within-run gain in percentage points, not absolute timings.", "",
        "| Lane | Metric | Arm | Absolute median per block (ns) | B/A | Gain % | 95% ratio CI | Status |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for lane_id, lane in analysis["lanes"].items():
        arm_absolute = lane.get("arm_absolute", {})
        metric = f"{lane.get('metric', 'latency')} ({lane.get('unit', 'ns')}; {lane.get('direction', 'lower')} better)"
        for arm, values in arm_absolute.items():
            comparison = lane.get("comparisons", {}).get(arm)
            if comparison is None:
                comparison = {"status": "REFERENCE"}
            interval = comparison.get("ratio_ci_95")
            formatted = f"[{_cell(interval[0])}, {_cell(interval[1])}]" if isinstance(interval, list) and len(interval) == 2 else "—"
            lines.append("| " + " | ".join(map(_cell, (
                lane_id, metric, arm, values.get("median_block_value"),
                comparison.get("ratio_b_over_a"), comparison.get("gain_percent"),
                formatted, comparison.get("status"),
            ))) + " |")
        if lane.get("excluded_blocks"):
            lines.append(f"\nExcluded whole blocks for `{_cell(lane_id)}`: {_cell(lane['excluded_blocks'])}.")
    if result.get("index_metrics"):
        lines.extend(["", "## Indexing, commit and size", "",
                      "| Arm | Corpus | Insert ms | Commit ms | Open ms | Index bytes |",
                      "| --- | ---: | ---: | ---: | ---: | ---: |"])
        for arm, corpora in result["index_metrics"].items():
            for n, values in corpora.items():
                lines.append("| " + " | ".join(map(_cell, (
                    arm, n, values.get("index_ns", 0) / 1e6,
                    values.get("commit_ns", 0) / 1e6,
                    values.get("reopen_ns", 0) / 1e6,
                    values.get("index_bytes"),
                ))) + " |")
    if result.get("throughput_metrics"):
        lines.extend(["", "## Serial throughput (steady warm session)", "",
                      "| Arm | Lane | Requests | Serial ops/s | Status |",
                      "| --- | --- | ---: | ---: | --- |"])
        for arm, row in result["throughput_metrics"].items():
            lines.append("| " + " | ".join(map(_cell, (
                arm, row.get("lane_id"), row.get("requests"),
                row.get("serial_ops_per_second"), row.get("status"),
            ))) + " |")
    lines.extend(["", "## Method and limitations", "",
                  f"- Estimator: `{_cell(analysis.get('estimator'))}`",
                  f"- Uncertainty: `{_cell(analysis.get('bootstrap_method'))}`",
                  f"- Source/build/host context: `{_cell(result.get('context', {}))}`",
                  "- Process-cold does not necessarily mean cold operating-system page cache.",
                  "- NON_COMPARABLE lanes are excluded from combined claims and ranking.",
                  "- A slowdown or INCONCLUSIVE result is evidence, not a pipeline error.",
                  "", "## Run notes", "", _cell(result.get("notes", "None")), ""])
    return "\n".join(lines)


def replay_to_markdown(path: Path) -> str:
    """Return ephemeral presentation of saved results; save no third artifact."""
    return render_report(load_result(path))
