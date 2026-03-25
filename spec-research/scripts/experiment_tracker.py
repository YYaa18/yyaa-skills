#!/usr/bin/env python3
"""
experiment_tracker.py — Persistent experiment state for spec-research

Manages the experiment state file (SPEC.md + .spec-research-state.json):
- Tracks all experiment runs with commit, metric, status
- Maintains best result and history
- Supports pause/resume of continuous runs
- Provides structured data for both AI and --web visualization

Usage:
    from experiment_tracker import ExperimentTracker
    tracker = ExperimentTracker(project_dir)
    tracker.init(baseline_value=0.0421, spec={...})
    tracker.record(commit="abc123", metric_value=0.038, description="switch to dict")
    best = tracker.get_best()
    state = tracker.get_state()
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


STATE_FILE = ".spec-research-state.json"


class ExperimentTracker:
    """Manages persistent experiment state."""

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.state_file = self.project_dir / STATE_FILE
        self.spec_file = self.project_dir / "SPEC.md"
        self._state: Optional[dict] = None

    # ------------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------------

    def _load(self) -> dict:
        if self._state is not None:
            return self._state
        if self.state_file.exists():
            self._state = json.loads(self.state_file.read_text())
        else:
            self._state = {"experiments": [], "best": None, "baseline": None,
                          "init_time": None, "last_run": None, "run_count": 0,
                          "consecutive_no_improve": 0, "status": "initialized"}
        return self._state

    def _save(self):
        self.state_file.write_text(json.dumps(self._state, indent=2, ensure_ascii=False))

    # ------------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------------

    def init(self, baseline_value: float, spec: dict):
        """Initialize tracking with baseline measurement."""
        state = self._load()
        state["baseline"] = baseline_value
        state["spec"] = {
            "primary_metric": spec.get("primary_metric", "score"),
            "target_delta": spec.get("target_delta", 10),
            "max_experiments": spec.get("max_experiments", 20),
            "budget_seconds": spec.get("budget_seconds", 60),
            "metric_direction": "lower_is_better" if spec.get("primary_metric") in [
                "latency", "memory", "error_rate", "cost", "line_count", "token_count"
            ] else "higher_is_better",
        }
        state["init_time"] = datetime.now(timezone.utc).isoformat()
        state["status"] = "baseline_set"
        self._save()
        self._update_spec_header(baseline_value)

    def _update_spec_header(self, baseline_value: float):
        """Update SPEC.md header with baseline and status."""
        if not self.spec_file.exists():
            return
        content = self.spec_file.read_text()
        # Update baseline value in SPEC.md
        if "Baseline value:" in content:
            import re
            content = re.sub(
                r"Baseline value:\*\* [^<\n]+",
                f"Baseline value:** `{baseline_value}`",
                content
            )
        # Add status section if not present
        if "## Research Status" not in content:
            status_section = "\n\n## Research Status\n\n"
            status_section += f"- **Status:** baseline_set\n"
            status_section += f"- **Baseline:** `{baseline_value}`\n"
            status_section += f"- **Best:** `{baseline_value}`\n"
            status_section += f"- **Experiments:** 0\n"
            status_section += f"- **Last run:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            # Insert before anti-patterns section or at end
            if "## Anti-Patterns" in content:
                content = content.replace("## Anti-Patterns", status_section + "\n## Anti-Patterns")
            else:
                content += status_section
        self.spec_file.write_text(content)

    # ------------------------------------------------------------------------
    # Record
    # ------------------------------------------------------------------------

    def record(self, commit: str, metric_value: float, description: str,
              experiment_num: Optional[int] = None) -> dict:
        """Record an experiment result."""
        state = self._load()
        spec = state.get("spec", {})
        direction = spec.get("metric_direction", "lower_is_better")
        baseline = state.get("baseline") or 0

        if baseline and baseline != 0:
            if direction == "lower_is_better":
                delta = metric_value - baseline
                delta_pct = (delta / baseline) * 100
            else:
                delta = metric_value - baseline
                delta_pct = (delta / baseline) * 100 if baseline != 0 else 0
        else:
            delta = 0.0
            delta_pct = 0.0

        # Determine if improved (for lower_is_better: metric decreased = improved)
        if direction == "lower_is_better":
            improved = metric_value < baseline if baseline else False
        else:
            improved = metric_value > baseline if baseline else False

        status = "improve" if improved else ("baseline" if experiment_num == 0 else "no_improve")

        exp = {
            "commit": commit,
            "metric": spec.get("primary_metric", "score"),
            "value": metric_value,
            "delta": round(delta, 8),
            "delta_pct": round(delta_pct, 4),
            "status": status,
            "description": description,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        state["experiments"].append(exp)
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        state["run_count"] = state.get("run_count", 0) + 1

        if improved:
            state["best"] = exp.copy()
            state["consecutive_no_improve"] = 0
        else:
            state["consecutive_no_improve"] = state.get("consecutive_no_improve", 0) + 1

        self._save()
        self._update_spec_progress()
        return exp

    def _update_spec_progress(self):
        """Update SPEC.md with latest progress."""
        if not self.spec_file.exists():
            return
        state = self._load()
        content = self.spec_file.read_text()

        best_val = state.get("best", {}).get("value") if state.get("best") else state.get("baseline")
        run_count = state.get("run_count", 0)
        consecutive = state.get("consecutive_no_improve", 0)
        last_run = state.get("last_run", "—")

        if best_val is None:
            best_val = state.get("baseline")
        if best_val is not None:
            best_val = f"`{best_val:.6f}`"

        import re
        # Update Research Status section
        replacements = [
            (r"- \*\*Status:\*\* [^\n]+", f"- **Status:** {state.get('status', 'running')}"),
            (r"- \*\*Best:\*\* [^\n]+", f"- **Best:** {best_val or '—'}"),
            (r"- \*\*Experiments:\*\* \d+", f"- **Experiments:** {run_count}"),
            (r"- \*\*Last run:\*\* [^\n]+", f"- **Last run:** {last_run[:16]}"),
            (r"- \*\*Consecutive no-improve:\*\* \d+", f"- **Consecutive no-improve:** {consecutive}"),
        ]
        for pattern, replacement in replacements:
            content = re.sub(pattern, replacement, content)

        # Update Results Log
        if "## Results Log" in content:
            # Find and replace results table
            results_start = content.find("## Results Log")
            results_end = content.find("\n##", results_start + 1)
            if results_end == -1:
                results_end = len(content)
            old_results = content[results_start:results_end]
        else:
            old_results = None

        new_results = self._generate_results_table()
        if old_results:
            content = content.replace(old_results, new_results)
        else:
            content += "\n\n" + new_results

        self.spec_file.write_text(content)

    def _generate_results_table(self) -> str:
        """Generate markdown results table from experiments."""
        state = self._load()
        exps = state.get("experiments", [])

        table = "## Results Log\n\n"
        table += "| # | Commit | Metric | Value | Delta | Δ% | Status | Description |\n"
        table += "|---|--------|--------|-------|-------|-------|--------|-------------|\n"

        baseline = state.get("baseline")
        for i, exp in enumerate(exps):
            val_str = f"{exp['value']:.6f}"
            delta_str = f"{exp['delta']:+.6f}"
            delta_pct = exp.get("delta_pct", 0)
            delta_pct_str = f"{delta_pct:+.2f}%"
            marker = " ★" if exp.get("status") == "improve" else ""
            desc = exp.get("description", "")[:40]
            table += f"| {i+1} | `{exp.get('commit','')[:7]}` | {exp.get('metric','score')} | {val_str} | {delta_str} | {delta_pct_str} | {exp.get('status','-')}{marker} | {desc} |\n"

        return table

    # ------------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------------

    def get_best(self) -> Optional[dict]:
        return self._load().get("best")

    def get_state(self) -> dict:
        """Return current state snapshot."""
        s = self._load()
        return {
            "status": s.get("status"),
            "baseline": s.get("baseline"),
            "best": s.get("best"),
            "run_count": s.get("run_count", 0),
            "consecutive_no_improve": s.get("consecutive_no_improve", 0),
            "experiments": s.get("experiments", []),
            "spec": s.get("spec"),
            "last_run": s.get("last_run"),
        }

    def is_success(self) -> bool:
        """Check if success criteria have been met."""
        state = self._load()
        best = state.get("best")
        baseline = state.get("baseline")
        spec = state.get("spec", {})
        target_delta = spec.get("target_delta", 10)

        if not best or not baseline or baseline == 0:
            return False

        direction = spec.get("metric_direction", "lower_is_better")
        delta_pct = abs(best.get("delta_pct", 0))

        if direction == "lower_is_better":
            return best["value"] < baseline * (1 - target_delta / 100)
        else:
            return best["value"] > baseline * (1 + target_delta / 100)

    def should_stop(self) -> bool:
        """Check if loop should stop (success, max experiments, or patience)."""
        state = self._load()
        spec = state.get("spec", {})
        max_exp = spec.get("max_experiments", 20)
        patience = 5  # consecutive no-improve before stopping

        if self.is_success():
            state["status"] = "success"
            self._save()
            return True

        if state.get("run_count", 0) >= max_exp:
            state["status"] = "exhausted"
            self._save()
            return True

        if state.get("consecutive_no_improve", 0) >= patience:
            state["status"] = "patience_exceeded"
            self._save()
            return True

        return False

    def set_status(self, status: str):
        state = self._load()
        state["status"] = status
        self._save()


if __name__ == "__main__":
    # CLI for quick state inspection
    import sys
    tracker = ExperimentTracker(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
    print(json.dumps(tracker.get_state(), indent=2))
