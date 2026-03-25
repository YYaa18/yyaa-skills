#!/usr/bin/env python3
"""
autoinit.py - Spec-Driven Research Project Initializer (v2)

Usage:
    python3 autoinit.py "goal" [--path /tmp] [--no-discover] [--run-baseline]
"""

import argparse, hashlib, json, os, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path


def run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd),
                         env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


METRIC_PATTERNS = [
    ("error rate", "error_rate", "lower is better"),
    ("throughput", "throughput", "higher is better"),
    ("latency", "latency", "lower is better"),
    ("response time", "latency", "lower is better"),
    ("performance", "throughput", "higher is better"),
    ("accuracy", "accuracy", "higher is better"),
    ("memory", "memory", "lower is better"),
    ("cpu usage", "cpu_usage", "lower is better"),
    ("fast", "speed", "higher is better"),
    ("faster", "speed", "higher is better"),
    ("speed", "speed", "higher is better"),
    ("slow", "latency", "lower is better"),
]


def parse_goal(goal):
    spec = {
        "goal_parsed": goal.strip(),
        "primary_metric": "score",
        "metrics": [],
        "baseline_value": "<measure first>",
        "budget_per_experiment": "60 seconds",
        "max_experiments": 20,
        "target_delta": 10,
        "tolerance": 5,
        "mutable_files": "mutable/main.py",
        "direction": "higher is better",
        "domain": "generic",
    }
    goal_lower = goal.lower()
    seen = set()
    for kw, name, direction in METRIC_PATTERNS:
        if kw in goal_lower and name not in seen:
            spec["metrics"].append((name, direction))
            seen.add(name)
    if not spec["metrics"]:
        spec["metrics"] = [("score", "higher is better")]
    spec["primary_metric"] = spec["metrics"][0][0]
    spec["direction"] = spec["metrics"][0][1]
    if any(x in goal_lower for x in ["python", "py ", "function", "script"]):
        spec["domain"] = "python"
        spec["mutable_files"] = "mutable/main.py"
    elif any(x in goal_lower for x in ["javascript", "js", "node", "typescript"]):
        spec["domain"] = "javascript"
        spec["mutable_files"] = "mutable/main.js"
    elif any(x in goal_lower for x in ["api", "http", "request", "endpoint"]):
        spec["domain"] = "api"
        spec["mutable_files"] = "mutable/client.py"
    elif any(x in goal_lower for x in ["shell", "bash"]):
        spec["domain"] = "shell"
        spec["mutable_files"] = "mutable/main.sh"
    if "minute" in goal_lower:
        m = re.search(r"(\d+)\s*minute", goal_lower)
        if m:
            spec["budget_per_experiment"] = "%d seconds" % (int(m.group(1)) * 60)
    elif "second" in goal_lower:
        m = re.search(r"(\d+)\s*second", goal_lower)
        if m:
            spec["budget_per_experiment"] = "%s seconds" % m.group(1)
    elif "overnight" in goal_lower:
        spec["budget_per_experiment"] = "300 seconds"
        spec["max_experiments"] = 100
    mult_match = re.search(r"(\d+(?:\.\d+)?)\s*x\s*(?:faster|improvement)", goal_lower)
    if mult_match:
        mult = float(mult_match.group(1))
        spec["target_delta"] = int(round((1 - 1/mult) * 100))
    else:
        pct_match = re.search(r"(?:by\s+)?(\d+)%\s*(?:improvement|better|faster|latency|speed|accuracy)?", goal_lower)
        if pct_match:
            pct = int(pct_match.group(1))
            if pct <= 100:
                spec["target_delta"] = pct
    return spec


def build_spec_md(spec, project_name, discovered=None):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    metrics_rows = ""
    for i, (name, direction) in enumerate(spec["metrics"], 1):
        marker = " ★" if name == spec["primary_metric"] else ""
        metrics_rows += "| %d | %s%s | %s | | |\n" % (i, name, marker, direction)
    disc = ""
    if discovered:
        eps = ", ".join([e["path"] for e in discovered.get("entry_points", [])[:3]]) or "none found"
        cats = ", ".join(set(m["category"] for m in discovered.get("metric_points", []))) or "none detected"
        disc = ("\n## Discovered Context\n\n"
                "- **Language:** %s\n"
                "- **Entry points:** %s\n"
                "- **Existing metrics:** %s\n") % (
                    discovered.get("language", "unknown"), eps, cats)
    eval_code = (
        "```python\n"
        "#!/usr/bin/env python3\n"
        "import subprocess, sys, os, re\n"
        "\n"
        "METRIC_CMD = [sys.executable, 'mutable/main.py']\n"
        "\n"
        "def evaluate():\n"
        "    r = subprocess.run(METRIC_CMD, capture_output=True, text=True,\n"
        "                       cwd=os.path.dirname(os.path.dirname(__file__)), timeout=30)\n"
        "    for line in r.stdout.splitlines():\n"
        "        if line.startswith('metric='):\n"
        "            return float(line.split('=')[1])\n"
        "    floats = re.findall(r'[-+]?[\\d.]+', r.stdout)\n"
        "    return float(floats[-1]) if floats else 0.0\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    print('metric=' + str(evaluate()))\n"
        "```")
    template = (
        "# SPEC.md - %s\n\n"
        "> Auto-generated by spec-research autoinit - %s\n"
        "> Goal: %s\n\n"
        "## 1. Goal\n\n%s\n%s\n"
        "## 2. Metrics\n\n"
        "| # | Metric | Direction | Measurement | Target Delta |\n"
        "|---|--------|-----------|-------------|---------------|\n%s\n"
        "**Primary metric:** `%s` (%s)\n"
        "**Target:** improved by >= %d%% vs baseline\n\n"
        "## 3. Baseline\n\n"
        "```bash\n"
        "python3 fixed/evaluate.py\n"
        "# expects: metric=<float>\n"
        "```\n\n"
        "Baseline: **%s**\n\n"
        "## 4. Experiment Loop\n\n"
        "- **Budget per experiment:** %s\n"
        "- **Max experiments:** %d\n"
        "- **Mutable file(s):** `%s`\n"
        "- **Git strategy:** Each experiment in a branch; good results merged, bad discarded\n\n"
        "## 5. Success Criteria\n\n"
        "- Done: Primary metric improved by >= %d%% vs baseline\n"
        "- Done: %d experiments exhausted\n"
        "- Stopped: 5 consecutive no-improve, or regression >50%%\n\n"
        "## 6. Evaluation Script (fixed/evaluate.py)\n\n%s\n\n"
        "## 7. Constraints\n\n"
        "1. `fixed/` is NEVER modified\n"
        "2. Each experiment = 1 git branch\n"
        "3. Regressed = branch deleted; Improved = merge to main\n"
        "4. No new dependencies without written approval\n"
        "5. Metric must print `metric=<float>` to stdout\n\n"
        "## Research Status\n\n"
        "- **Status:** initialized\n"
        "- **Baseline:** %s\n"
        "- **Best:** %s\n"
        "- **Experiments:** 0\n\n"
        "## Results Log\n\n"
        "| # | Commit | Metric | Value | Delta | Status | Description |\n"
        "|---|--------|--------|-------|-------|--------|-------------|\n"
    ) % (project_name, now, spec["goal_parsed"],
         spec["goal_parsed"], disc,
         metrics_rows,
         spec["primary_metric"], spec["direction"], spec["target_delta"],
         spec["baseline_value"],
         spec["budget_per_experiment"], spec["max_experiments"], spec["mutable_files"],
         spec["target_delta"], spec["max_experiments"],
         eval_code,
         spec["baseline_value"], spec["baseline_value"])
    return template


def build_discover_report(repo):
    LANG_EXT = {".py": "python", ".js": "javascript", ".ts": "typescript",
                 ".go": "go", ".rs": "rust", ".sh": "shell"}
    lang_counts = {}
    for f in repo.rglob("*"):
        if f.is_file() and not any(p in str(f) for p in [".git", "node_modules", "__pycache__"]):
            ext = f.suffix.lower()
            lang = LANG_EXT.get(ext)
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
    primary = max(lang_counts, key=lang_counts.get) if lang_counts else "unknown"
    eps = []
    if primary == "python":
        for f in repo.rglob("*.py"):
            try:
                c = f.read_text(errors="ignore")
                if any(kw in c for kw in ["if __name__", "argparse", "def main"]):
                    eps.append({"path": str(f.relative_to(repo)), "reason": "entry point"})
            except Exception:
                pass
    mp = []
    patterns = {"time": [".perf_counter(", "time.time("],
                "memory": ["memory_info(", "tracemalloc"],
                "throughput": ["ops/sec", "requests/sec"]}
    for f in repo.rglob("*"):
        if not f.is_file() or f.stat().st_size > 500_000:
            continue
        try:
            c = f.read_text(errors="ignore")
            for cat, pats in patterns.items():
                for pat in pats:
                    if pat in c:
                        mp.append({"file": str(f.relative_to(repo)), "category": cat})
                        break
        except Exception:
            pass
    return {"language": primary, "entry_points": eps[:5], "metric_points": mp[:10]}


def create_project(base_path, goal, spec, discovered=None):
    words = goal.split()[:4]
    name = re.sub(r"[^\w]+", "-", "_".join(w.strip("'\".,") for w in words if w.strip("'\".,"))).lower()
    suffix = hashlib.md5(goal.encode()).hexdigest()[:6]
    proj = base_path / ("spec-research-%s-%s" % (name, suffix[:6]))
    proj.mkdir(parents=True, exist_ok=True)
    for d in ["fixed", "mutable", "results", "experiments"]:
        (proj / d).mkdir(exist_ok=True)
    (proj / "SPEC.md").write_text(build_spec_md(spec, proj.name, discovered))
    eval_py = (
        "#!/usr/bin/env python3\n"
        "import subprocess, sys, os, re\n"
        "METRIC_CMD = [sys.executable, 'mutable/main.py']\n"
        "def evaluate():\n"
        "    r = subprocess.run(METRIC_CMD, capture_output=True, text=True,\n"
        "                       cwd=os.path.dirname(os.path.dirname(__file__)), timeout=30)\n"
        "    for line in r.stdout.splitlines():\n"
        "        if line.startswith('metric='):\n"
        "            return float(line.split('=')[1])\n"
        "    floats = re.findall(r'[-+]?[\\d.]+', r.stdout)\n"
        "    return float(floats[-1]) if floats else 0.0\n"
        "if __name__ == '__main__':\n"
        "    print('metric=' + str(evaluate()))\n"
    )
    (proj / "fixed" / "evaluate.py").write_text(eval_py)
    ext = {"python": ".py", "javascript": ".js", "api": ".py", "shell": ".sh"}.get(spec["domain"], ".py")
    stub = (
        "# mutable/main.py\n\n"
        "import time\n\n"
        "def run():\n"
        "    start = time.perf_counter()\n"
        "    # === YOUR CODE HERE ===\n"
        "    elapsed = time.perf_counter() - start\n"
        "    print('metric=' + str(elapsed))\n\n"
        "if __name__ == '__main__':\n"
        "    run()\n"
    )
    (proj / "mutable" / ("main" + ext)).write_text(stub)
    (proj / "results" / "results.tsv").write_text("commit\tmetric\tvalue\tdelta\tstatus\tdescription\n")
    (proj / "experiments" / "program.md").write_text(
        "# Experiments Program\n\n## Goal\n%s\n\n## Workflow\n"
        "1. Read SPEC.md and fixed/evaluate.py\n"
        "2. Get strategy: python3 <skill>/scripts/strategy_advisor.py %s --json\n"
        "3. Apply change to %s\n"
        "4. Run: python3 fixed/evaluate.py\n"
        "5. Record result; merge if improved, discard if regressed\n"
        "6. Check stop criteria -> loop or report\n" % (goal, proj.name, spec["mutable_files"]))
    (proj / "README.md").write_text(
        "# %s\n\n"
        "Run:\n"
        "  python3 <skill>/scripts/run_loop.py . --continuous --agent codex\n"
        "  python3 <skill>/scripts/run_loop.py . --web  # dashboard\n" % proj.name)
    budget_sec = int(re.search(r"\d+", spec["budget_per_experiment"]).group())
    state = {
        "experiments": [], "best": None, "baseline": None,
        "init_time": datetime.now(timezone.utc).isoformat(),
        "last_run": None, "run_count": 0,
        "consecutive_no_improve": 0, "status": "initialized",
        "spec": {
            "primary_metric": spec["primary_metric"],
            "target_delta": spec["target_delta"],
            "max_experiments": spec["max_experiments"],
            "budget_seconds": budget_sec,
            "metric_direction": "lower_is_better",
        },
        "goal": spec["goal_parsed"],
    }
    (proj / ".spec-research-state.json").write_text(json.dumps(state, indent=2) + "\n")
    run(["git", "init"], proj)
    run(["git", "add", "."], proj)
    run(["git", "commit", "-m", "chore: initial spec-research project"], proj)
    run(["git", "checkout", "-b", "main"], proj)
    return proj, state


def main():
    p = argparse.ArgumentParser()
    p.add_argument("goal")
    p.add_argument("--path", default=".")
    p.add_argument("--no-discover", action="store_true")
    p.add_argument("--run-baseline", action="store_true")
    p.add_argument("--target", default=None)
    a = p.parse_args()
    goal = a.goal.strip().strip("'\"")
    base = Path(a.path).resolve()
    spec = parse_goal(goal)
    print("Goal:", goal, file=sys.stderr)
    print("Metric:", spec["primary_metric"], "({})".format(spec["direction"]), file=sys.stderr)
    print("Target: >={}%".format(spec["target_delta"]), file=sys.stderr)
    disc = None
    if not a.no_discover:
        tp = Path(a.target).resolve() if a.target else base
        if tp.exists() and tp.is_dir():
            print("Discovering:", tp, file=sys.stderr)
            try:
                disc = build_discover_report(tp)
                print("Language:", disc["language"], file=sys.stderr)
            except Exception as e:
                print("Discovery failed:", str(e), file=sys.stderr)
    print("Creating project...", file=sys.stderr)
    proj, state = create_project(base, goal, spec, disc)
    print("Project:", proj, file=sys.stderr)
    if a.run_baseline:
        print("Measuring baseline...", file=sys.stderr)
        r = run([sys.executable, str(proj / "fixed" / "evaluate.py")], proj)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                m = re.search(r"metric=([-+]?\d+\.?\d*)", line)
                if m:
                    bv = float(m.group(1))
                    print("Baseline:", bv, file=sys.stderr)
                    state["baseline"] = bv
                    state["status"] = "baseline_set"
                    (proj / ".spec-research-state.json").write_text(json.dumps(state, indent=2) + "\n")
                    run(["git", "add", "."], proj)
                    run(["git", "commit", "-m", "chore: baseline %s" % bv], proj)
        else:
            print("Baseline failed:", r.stderr[:200], file=sys.stderr)
    print("Done. cd", proj, file=sys.stderr)


if __name__ == "__main__":
    main()
