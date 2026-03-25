#!/usr/bin/env python3
"""
run_loop.py — Spec-Driven Experiment Loop with Branch Isolation + Web Dashboard

Full workflow:
  1. Read SPEC.md + current state
  2. Get strategy recommendation from strategy_advisor.py
  3. Git branch for this experiment
  4. Invoke coding agent (Codex/Claude Code) with concrete prompt
  5. Run evaluation
  6. If improved → merge branch; if regressed → delete branch
  7. Update state + SPEC.md
  8. Check success/stop criteria → loop or exit
  9. Optional: start HTTP dashboard (--web)

Usage:
    cd <project-dir>
    python3 <skill>/scripts/run_loop.py . [--max N] [--budget SEC] [--continuous] [--web]

    # With Codex fully automated:
    python3 run_loop.py . --continuous --agent codex

    # With Claude Code:
    python3 run_loop.py . --continuous --agent claude

    # Web dashboard only:
    python3 run_loop.py . --web
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_BUDGET = 60
SKILL_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from experiment_tracker import ExperimentTracker
from strategy_advisor import generate_experiment_prompt, STRATEGIES

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>spec-research dashboard</title>
<style>
  body { font-family: -apple-system, sans-serif; margin: 0; padding: 20px; background: #0f0f0f; color: #e0e0e0; }
  h1 { color: #7dd3fc; font-size: 1.4em; margin-bottom: 5px; }
  .meta { color: #94a3b8; font-size: 0.85em; margin-bottom: 20px; }
  .card { background: #1a1a2e; border-radius: 8px; padding: 16px; margin-bottom: 16px; border: 1px solid #2a2a4e; }
  .metric { font-size: 2em; font-weight: bold; color: #7dd3fc; }
  .label { color: #94a3b8; font-size: 0.75em; text-transform: uppercase; }
  .delta { font-size: 1.2em; }
  .delta.pos { color: #4ade80; } .delta.neg { color: #f87171; }
  .bar { background: #2a2a4e; border-radius: 4px; height: 8px; margin: 8px 0; }
  .bar-fill { border-radius: 4px; height: 8px; background: #7dd3fc; transition: width 0.3s; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
  th { text-align: left; color: #94a3b8; border-bottom: 1px solid #2a2a4e; padding: 6px; }
  td { padding: 6px; border-bottom: 1px solid #1a1a2e; }
  tr:hover { background: #1e1e3a; }
  .status-improve { color: #4ade80; } .status-baseline { color: #94a3b8; }
  .status-no_improve { color: #f87171; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.75em; background: #2a2a4e; }
  .running { animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
  .controls { margin-bottom: 16px; }
  .controls button { background: #7dd3fc; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; margin-right: 8px; font-weight: bold; }
  .controls button.stop { background: #f87171; }
</style>
</head><body>
<h1>🔬 spec-research Dashboard</h1>
<div class="meta" id="meta"></div>
<div class="controls">
  <button onclick="refresh()">↻ Refresh</button>
  <button onclick="toggle()">▶/⏸ Auto-refresh</button>
</div>
<div id="cards"></div>
<div id="table"></div>
<script>
let auto = false, t = null;
const origFetch = fetch;
function refresh() { origFetch('/data').then(r=>r.json()).then(render); }
function toggle() { auto=!auto; if(auto) t=setInterval(refresh,3000); else clearInterval(t); }
async function render(d) {
  const s=d.state, exps=s.experiments||[], best=s.best||{};
  document.getElementById('meta').innerHTML =
    `Project: <b>${d.project_name}</b> · Metric: <b>${s.spec?.primary_metric||'?'}</b> · Direction: <b>${s.spec?.metric_direction||'?'}</b> · Budget: <b>${s.spec?.budget_seconds||60}s</b>`;

  const baseline=s.baseline, bestVal=best.value;
  let pct=0;
  if(baseline && bestVal) {
    const delta=bestVal-baseline;
    pct=Math.abs(delta/baseline*100).toFixed(1);
  }

  let cards=`<div class="card"><div class="label">Baseline</div><div class="metric">${baseline||'—'}</div></div>`;
  if(bestVal) cards+=`<div class="card"><div class="label">Best (★)</div><div class="metric">${bestVal.toFixed(6)}</div></div>`;
  if(bestVal) cards+=`<div class="card"><div class="label">Improvement</div><div class="delta ${best&&bestVal<baseline?'pos':'neg'}">${bestVal<baseline?'↓':'↑'}${pct}%</div></div>`;
  cards+=`<div class="card"><div class="label">Experiments</div><div class="metric">${exps.length}</div><div class="bar"><div class="bar-fill" style="width:${Math.min(100,exps.length/(s.spec?.max_experiments||20)*100)}%"></div></div></div>`;
  cards+=`<div class="card"><div class="label">Status</div><div class="badge ${s.status=='running'?'running':''}">${s.status||'—'}</div></div>`;
  document.getElementById('cards').innerHTML=cards;

  let table='<table><tr><th>#</th><th>Commit</th><th>Value</th><th>Δ</th><th>Δ%</th><th>Status</th><th>Description</th></tr>';
  exps.forEach((e,i)=>{
    const delta=e.value-baseline;
    const dpct=(delta/baseline*100).toFixed(2);
    table+=`<tr>
      <td>${i+1}</td>
      <td><code>${(e.commit||'').slice(0,7)}</code></td>
      <td>${e.value?.toFixed(6)}</td>
      <td class="delta ${delta<0?'pos':'neg'}">${delta>=0?'+':''}${(delta).toFixed(6)}</td>
      <td>${dpct}%</td>
      <td class="status-${e.status}">${e.status}</td>
      <td>${(e.description||'').slice(0,50)}</td>
    </tr>`;
  });
  table+='</table>';
  document.getElementById('table').innerHTML=table;
}
refresh();
let orig = document.querySelector;
setInterval(refresh, auto ? 3000 : 999999);
</script></body></html>"""


class DashboardHandler(SimpleHTTPRequestHandler):
    """HTTP dashboard for experiment visualization."""

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())
        elif self.path == "/data":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            state = self.server.tracker.get_state()
            self.wfile.write(json.dumps({
                "project_name": self.server.project_name,
                "state": state,
            }).encode())
        else:
            super().do_GET()

    def log_message(self, format, *args):
        pass  # Silence logs


def run_git(cmd: list, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(cwd),
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    )


def get_current_metric(project_dir: Path) -> float | None:
    eval_path = project_dir / "fixed" / "evaluate.py"
    if not eval_path.exists():
        return None
    r = run_git([sys.executable, str(eval_path)], project_dir)
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        m = re.search(r"metric=([-+]?[\d.]+)", line)
        if m:
            return float(m.group(1))
    floats = re.findall(r"[-+]?[\d.]+", r.stdout)
    return float(floats[-1]) if floats else None


def invoke_coding_agent(agent: str, prompt: str, project_dir: Path) -> bool:
    """Invoke a coding agent (codex/claude) to apply the experiment change."""

    if agent == "codex":
        cmd = [
            "codex", "exec",
            "--full-auto",
            f"--goal {prompt}"
        ]
        workdir = str(project_dir)
    elif agent == "claude":
        cmd = [
            sys.executable, "-c",
            f"import subprocess; subprocess.run(['claude', '-p', '{prompt.replace(chr(39), chr(39)*3)}'], cwd='{project_dir}')"
        ]
        workdir = str(project_dir)
    else:
        print(f"⚠️  Unknown agent '{agent}'. Apply the change manually, then run evaluate.py", file=sys.stderr)
        return False

    try:
        r = run_git(cmd, project_dir)
        return r.returncode == 0
    except Exception as e:
        print(f"⚠️  Agent failed: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Branch-based experiment loop
# ---------------------------------------------------------------------------

def run_experiment_branch(project_dir: Path, experiment_num: int,
                          strategy_name: str, agent_prompt: str,
                          agent: str) -> tuple[bool, float | None]:
    """
    Run a single experiment in an isolated git branch.
    Returns (success, metric_value).
    """
    branch_name = f"exp/{experiment_num:03d}-{strategy_name.lower()}"

    # Create experiment branch
    r = run_git(["git", "checkout", "-b", branch_name], project_dir)
    if r.returncode != 0:
        print(f"⚠️  Could not create branch {branch_name}: {r.stderr[:100]}", file=sys.stderr)
        # Fall back to working directory changes
        branch_name = None

    # Invoke coding agent to apply change
    print(f"🤖 Invoking {agent} with strategy: {strategy_name}", file=sys.stderr)
    applied = invoke_coding_agent(agent, agent_prompt, project_dir)

    if not applied:
        print(f"⚠️  Agent did not confirm change — attempting to run evaluation anyway", file=sys.stderr)

    # Measure metric
    metric = get_current_metric(project_dir)

    # Commit or stage changes
    if branch_name:
        run_git(["git", "add", "-A"], project_dir)
        run_git(["git", "commit", "-m", f"exp: {experiment_num} {strategy_name}"], project_dir)

    return True, metric


def merge_or_discard(project_dir: Path, experiment_num: int,
                     strategy_name: str, improved: bool,
                     baseline: float, current: float,
                     branch_metric: float | None):
    """Merge good results, discard bad ones."""

    branch_name = f"exp/{experiment_num:03d}-{strategy_name.lower()}"

    if improved and branch_metric is not None:
        # Merge into main
        print(f"  ✅ Improved: {baseline:.6f} → {branch_metric:.6f} — merging", file=sys.stderr)
        run_git(["git", "checkout", "main"], project_dir)
        r = run_git(["git", "merge", branch_name, "--no-ff", "-m",
                     f"merge: exp {experiment_num} {strategy_name} improved {baseline:.6f}→{branch_metric:.6f}"],
                    project_dir)
        if r.returncode == 0:
            print(f"  ✅ Branch merged", file=sys.stderr)
        else:
            print(f"  ⚠️  Merge conflict: {r.stderr[:200]}", file=sys.stderr)
            run_git(["git", "merge", "--abort"], project_dir)
            print(f"  ↩️  Manual merge needed — branch kept: {branch_name}", file=sys.stderr)
    else:
        # Discard: reset and delete branch
        print(f"  ❌ Regressed — discarding branch {branch_name}", file=sys.stderr)
        run_git(["git", "checkout", "main"], project_dir)
        run_git(["git", "branch", "-D", branch_name], project_dir)
        run_git(["git", "reset", "--hard"], project_dir)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_loop(project_dir: Path, agent: str, max_experiments: int | None,
             budget_seconds: int, continuous: bool, web: bool):
    tracker = ExperimentTracker(project_dir)
    spec_path = project_dir / "SPEC.md"
    mutable = project_dir / "mutable"

    if not spec_path.exists():
        print(f"❌ SPEC.md not found in {project_dir}", file=sys.stderr)
        sys.exit(1)

    # Load spec fields
    state = tracker.get_state()
    spec_fields = state.get("spec", {})
    baseline = state.get("baseline")
    direction = spec_fields.get("metric_direction", "lower_is_better")
    primary_metric = spec_fields.get("primary_metric", "score")
    max_exp = max_experiments or spec_fields.get("max_experiments", 20)

    # Initialize git main branch
    r = run_git(["git", "status"], project_dir)
    if "fatal" in r.stderr.lower() or r.returncode != 0:
        run_git(["git", "init"], project_dir)
        run_git(["git", "add", "."], project_dir)
        run_git(["git", "commit", "-m", "chore: initial spec-research project"], project_dir)
        run_git(["git", "checkout", "-b", "main"], project_dir)

    branches = r.stdout.splitlines()
    on_main = any("main" in b for b in branches)

    if not on_main:
        run_git(["git", "checkout", "-b", "main"], project_dir)

    # Measure baseline if not set
    if baseline is None:
        print("📏 Measuring baseline...", file=sys.stderr)
        baseline_val = get_current_metric(project_dir)
        if baseline_val is None:
            print("⚠️  Could not measure baseline. Is evaluate.py working?", file=sys.stderr)
            baseline_val = 0.0
        tracker.init(baseline_value=baseline_val, spec=spec_fields)
        baseline = baseline_val
        print(f"   Baseline: {baseline}", file=sys.stderr)
        run_git(["git", "add", "."], project_dir)
        run_git(["git", "commit", "-m", f"chore: baseline measurement {baseline:.6f}"], project_dir)
        tracker.set_status("running")
    else:
        tracker.set_status("running")

    print(f"\n🚀 Starting experiment loop (agent={agent}, max={max_exp})\n", file=sys.stderr)

    # Start web dashboard if requested
    if web:
        server = HTTPServer(("localhost", 19842), DashboardHandler)
        server.tracker = tracker
        server.project_name = project_dir.name
        t = threading.Thread(target=lambda: server.serve_forever(), daemon=True)
        t.start()
        webbrowser.open("http://localhost:19842")
        print("🌐 Dashboard at http://localhost:19842", file=sys.stderr)

    exp_num = state.get("run_count", 0)
    success = False

    while exp_num < max_exp:
        # Check stop conditions
        if tracker.should_stop():
            result_state = tracker.get_state()
            print(f"\n🏁 Loop ended: status={result_state.get('status')}", file=sys.stderr)
            break

        print(f"\n--- Experiment {exp_num + 1}/{max_exp} ---", file=sys.stderr)

        # Get strategy recommendation
        sys.path.insert(0, str(SKILL_DIR / "scripts"))
        from strategy_advisor import recommend_strategy, analyze_history, analyze_code

        exps = tracker.get_state().get("experiments", [])
        hist = analyze_history(exps)
        code = analyze_code(mutable)
        strategy = recommend_strategy(hist, code, None, direction)

        strat_name = strategy["strategy"]
        print(f"   Strategy: {strat_name} (confidence: {strategy['confidence']})", file=sys.stderr)
        print(f"   Reason: {strategy['reason']}", file=sys.stderr)

        # Generate agent prompt
        prompt = generate_experiment_prompt(strat_name, STRATEGIES.get(strat_name, {}),
                                          mutable, primary_metric, direction)

        # Run experiment in branch
        _, metric = run_experiment_branch(project_dir, exp_num + 1, strat_name,
                                         prompt, agent)

        if metric is None:
            print("⚠️  Evaluation failed — skipping this experiment", file=sys.stderr)
            exp_num += 1
            continue

        # Determine if improved
        if direction == "lower_is_better":
            improved = metric < baseline
        else:
            improved = metric > baseline

        # Commit result
        current_commit = run_git(["git", "rev-parse", "--short", "HEAD"], project_dir).stdout.strip()
        exp_record = tracker.record(
            commit=current_commit,
            metric_value=metric,
            description=strat_name
        )

        # Merge or discard
        merge_or_discard(project_dir, exp_num + 1, strat_name,
                        exp_record["status"] == "improve",
                        baseline, metric, metric)

        exp_num += 1

        # If not continuous, prompt user for next step
        if not continuous:
            print(f"\n   Metric: {metric:.6f} | Status: {exp_record['status']}", file=sys.stderr)
            resp = input("Continue? [Y/n/q]: ").strip().lower()
            if resp == "q":
                tracker.set_status("paused")
                break
            elif resp == "n":
                tracker.set_status("paused")
                break

    # Final report
    final_state = tracker.get_state()
    best = final_state.get("best")
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"🏁 Research complete: {final_state.get('status')}", file=sys.stderr)
    print(f"   Baseline: {baseline}", file=sys.stderr)
    if best:
        print(f"   Best: {best['value']} (delta: {best['delta']:+.6f})", file=sys.stderr)
    print(f"   Experiments: {final_state.get('run_count')}", file=sys.stderr)
    print(f"   See: {spec_path} or http://localhost:19842", file=sys.stderr)

    if web:
        print("   Press Ctrl+C to stop dashboard server", file=sys.stderr)

    return final_state


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="spec-research experiment loop")
    parser.add_argument("project", nargs="?", default=".", help="Project directory")
    parser.add_argument("--max", type=int, default=None, help="Max experiments override")
    parser.add_argument("--budget", type=int, default=None, help="Budget seconds override")
    parser.add_argument("--continuous", action="store_true", help="Run continuously without prompting")
    parser.add_argument("--web", action="store_true", help="Start web dashboard")
    parser.add_argument("--agent", default="codex",
                       choices=["codex", "claude", "manual"],
                       help="Coding agent to use")
    args = parser.parse_args()

    project_dir = Path(args.project).resolve()
    budget = args.budget or DEFAULT_BUDGET

    run_loop(project_dir, agent=args.agent, max_experiments=args.max,
             budget_seconds=budget, continuous=args.continuous, web=args.web)


if __name__ == "__main__":
    main()
