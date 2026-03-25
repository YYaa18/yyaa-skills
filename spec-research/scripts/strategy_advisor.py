#!/usr/bin/env python3
"""
strategy_advisor.py — Smarter experiment strategy selector for spec-research

Analyzes experiment history + code to recommend the next experiment strategy.
Not a simple rotation — uses actual analysis to pick the most likely successful path.

Usage:
    python3 strategy_advisor.py <project-dir> [--history results.tsv]
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


# Strategies with context about when they work best
STRATEGIES = {
    "PROFILE_GUIDED": {
        "name": "Profile-Guided Optimization",
        "description": "Identify hot paths via profiling, then target the exact bottleneck",
        "best_for": ["First non-trivial experiment", "No clear bottleneck known"],
        "priority": 1,
    },
    "SIMPLIFY": {
        "name": "Simplify & Remove",
        "description": "Remove unnecessary work: redundant calculations, unnecessary copies, dead code paths",
        "best_for": ["Code looks complex", "Previous experiments plateaued"],
        "priority": 2,
    },
    "ALGORITHM": {
        "name": "Better Algorithm / Data Structure",
        "description": "Replace O(n²) with O(n log n), list with dict/set, naive with optimized approach",
        "best_for": ["Loops inside loops", "Linear search in large datasets", "Repeated lookups"],
        "priority": 2,
    },
    "CACHE": {
        "name": "Memoize / Cache",
        "description": "Cache repeated computations, use functools.lru_cache, precompute at startup",
        "best_for": ["Same inputs seen repeatedly", "Expensive pure functions", "Lookup-heavy code"],
        "priority": 3,
    },
    "BATCH": {
        "name": "Batch Operations",
        "description": "Group I/O or compute: bulk DB writes vs row-by-row, batch syscalls",
        "best_for": ["DB/Cache operations in a loop", "File I/O in a loop", "Network calls in a loop"],
        "priority": 3,
    },
    "PARALLEL": {
        "name": "Parallelize",
        "description": "Use threading/multiprocessing/asyncio for independent parallel work",
        "best_for": ["Independent work items", "I/O-bound tasks", "Large data transforms"],
        "priority": 3,
    },
    "PRECOMPUTE": {
        "name": "Precompute at Startup",
        "description": "Move expensive calculations from request-time to initialization",
        "best_for": ["Data doesn't change between calls", "Startup cost acceptable"],
        "priority": 4,
    },
    "COMPILE": {
        "name": "Use Compiled / Native Extensions",
        "description": "Replace Python loops with numpy/cffi/numba/cython, or switch to compiled language",
        "best_for": ["Python loops on large data", "Numeric computation heavy"],
        "priority": 4,
    },
    "LAZY": {
        "name": "Lazy Evaluation",
        "description": "Defer expensive work until result is actually needed (generators, caching)",
        "best_for": ["Not all results always needed", "Eager computation on large datasets"],
        "priority": 4,
    },
}


def run(cmd: list, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


def analyze_code(mutable_path: Path) -> dict:
    """Analyze mutable code for patterns that suggest strategies."""
    findings = {
        "has_loops": False,
        "has_nested_loops": False,
        "has_dict_lookup": False,
        "has_list_search": False,
        "has_io_loop": False,
        "has_network": False,
        "has_cache": False,
        "has_numpy": False,
        "has_threading": False,
        "complexity_score": 0,
        "hot_paths": [],
    }

    main_file = mutable_path / "main.py"
    if not main_file.exists():
        return findings

    try:
        content = main_file.read_text(errors="ignore")
    except Exception:
        return findings

    lines = content.split("\n")

    # Loop detection
    for i, line in enumerate(lines):
        if re.search(r"\b(for|while)\b", line):
            findings["has_loops"] = True
            # Check for nested loops
            indent = len(line) - len(line.lstrip())
            for j in range(i+1, min(i+10, len(lines))):
                next_indent = len(lines[j]) - len(lines[j].lstrip())
                if next_indent > indent and re.search(r"\b(for|while)\b", lines[j]):
                    findings["has_nested_loops"] = True
                    break
        if re.search(r"\[.*\s+for\s+.*\s+in\s+", line):
            findings["has_list_search"] = True
        if re.search(r"\.get\(|dict\(|defaultdict", line):
            findings["has_dict_lookup"] = True
        if re.search(r"open\(|read\(|write\(|requests\.|http\.", line):
            findings["has_io_loop"] = True
        if re.search(r"lru_cache|cache|@cache|memoize", line):
            findings["has_cache"] = True
        if re.search(r"numpy|np\.|pandas|pd\.", line):
            findings["has_numpy"] = True
        if re.search(r"ThreadPool|ProcessPool|concurrent|threading|asyncio", line):
            findings["has_threading"] = True
        if re.search(r"import\s+requests|import\s+urllib|import\s+aiohttp", line):
            findings["has_network"] = True

    # Complexity heuristic
    complexity = 0
    complexity += findings["has_loops"] * 1
    complexity += findings["has_nested_loops"] * 2
    complexity += findings["has_list_search"] * 1
    complexity += findings["has_io_loop"] * 1
    complexity += findings["has_network"] * 1
    complexity += 1 if len(lines) > 100 else 0
    findings["complexity_score"] = complexity

    return findings


def analyze_history(experiments: list[dict]) -> dict:
    """Analyze experiment history to detect patterns."""
    if not experiments:
        return {"pattern": "cold_start", "plateaued": False, "last_improvement_at": None}

    recent = experiments[-5:] if len(experiments) >= 5 else experiments
    improvements = [e for e in recent if e.get("status") == "improve"]

    last_improve = None
    for e in reversed(experiments):
        if e.get("status") == "improve":
            last_improve = e
            break

    # Check if we're in a plateau (recent no-improve streak)
    recent_statuses = [e.get("status") for e in recent]
    plateaued = (
        len(recent_statuses) >= 3 and
        all(s != "improve" for s in recent_statuses)
    )

    return {
        "pattern": "improving" if improvements else "no_improvement",
        "plateaued": plateaued,
        "last_improvement": last_improve,
        "improvement_count": len(improvements),
        "total_experiments": len(experiments),
    }


def recommend_strategy(history_analysis: dict, code_analysis: dict,
                       current_best: Optional[float],
                       metric_direction: str) -> dict:
    """Recommend the next strategy based on analysis."""

    if history_analysis["pattern"] == "cold_start":
        # First experiment: always start with profile-guided
        return {
            "strategy": "PROFILE_GUIDED",
            "reason": "No history yet — profile first to find the real bottleneck",
            "confidence": "high",
        }

    if history_analysis["plateaued"]:
        # Plateaued: need a fundamentally different approach
        if not code_analysis["has_cache"] and not code_analysis["has_threading"]:
            return {
                "strategy": "PARALLEL",
                "reason": "Plateaued and no caching or parallelism detected — try parallelizing independent work",
                "confidence": "medium",
            }
        return {
            "strategy": "COMPILE",
            "reason": "Plateaued after multiple attempts — consider compiled extensions (numba/cython) or algorithm rewrite",
            "confidence": "low",
        }

    # General recommendations based on code analysis
    recommendations = []

    if code_analysis["has_nested_loops"]:
        recommendations.append(("ALGORITHM", 0.9,
            "Nested loops detected — algorithm change likely has highest impact"))

    if code_analysis["has_io_loop"] and not code_analysis["has_threading"]:
        recommendations.append(("BATCH", 0.8,
            "I/O in loop detected — batching can dramatically reduce overhead"))

    if not code_analysis["has_cache"]:
        recommendations.append(("CACHE", 0.7,
            "No caching detected — memoization often gives easy wins"))

    if code_analysis["has_numpy"] is False and code_analysis["complexity_score"] > 3:
        recommendations.append(("COMPILE", 0.6,
            "High complexity Python code — compiled extensions may help"))

    if not code_analysis["has_threading"] and (code_analysis["has_io_loop"] or code_analysis["has_network"]):
        recommendations.append(("PARALLEL", 0.7,
            "I/O-bound work without parallelism — threading/asyncio can hide latency"))

    if code_analysis["has_list_search"]:
        recommendations.append(("ALGORITHM", 0.8,
            "List search detected — dict/set O(1) lookup may replace O(n) search"))

    # Sort by confidence
    recommendations.sort(key=lambda x: x[1], reverse=True)

    if recommendations:
        name, confidence, reason = recommendations[0]
        return {
            "strategy": name,
            "reason": reason,
            "confidence": "high" if confidence > 0.8 else "medium" if confidence > 0.6 else "low",
        }

    # Fallback: simple rotation through remaining strategies
    return {
        "strategy": "SIMPLIFY",
        "reason": "No specific pattern detected — try simplifying the code",
        "confidence": "low",
    }


def generate_experiment_prompt(strategy_name: str, strategy: dict,
                               mutable_path: Path, metric: str,
                               direction: str) -> str:
    """Generate a concrete prompt for the coding agent."""

    main_file = mutable_path / "main.py"
    current_code = main_file.read_text(errors="ignore")[:500] if main_file.exists() else "(file not found)"

    prompts = {
        "PROFILE_GUIDED": f"""Apply profile-guided optimization to mutable/main.py:

1. Add timing to the current code to identify which lines take the most time
2. Run the code and print timing for each section: "section=<name> time=<ms>ms"
3. Identify the single hottest section
4. Optimize ONLY that section
5. Run evaluate.py and print "metric=<value>"

Current code (first 500 chars):
```
{current_code[:500]}
```

Focus on: where does time.time() or time.perf_counter() show the most elapsed time?""",

        "SIMPLIFY": f"""Simplify mutable/main.py:

1. Read the current code carefully
2. Identify and remove: redundant calculations, unnecessary list/dict copies, pointless abstractions, dead code paths
3. Keep functionality identical — only remove what's unnecessary
4. Run evaluate.py and print "metric=<value>"

Current code (first 500 chars):
```
{current_code[:500]}
```""",

        "ALGORITHM": f"""Improve the algorithm in mutable/main.py:

1. Read the current code
2. Look for: O(n²) loops that could be O(n), linear searches that could use dict/set, repeated work that could be precomputed
3. Replace with a more efficient approach
4. Keep the same output for the same input
5. Run evaluate.py and print "metric=<value>"

Current code (first 500 chars):
```
{current_code[:500]}
```""",

        "CACHE": f"""Add caching to mutable/main.py:

1. Read the current code
2. Identify pure functions (same input → same output) called repeatedly
3. Add @functools.lru_cache or manual caching
4. For non-hashable types, consider a class-level dict cache
5. Run evaluate.py and print "metric=<value>"

Note: Ensure the cached function is actually called multiple times with same args in a typical run.

Current code (first 500 chars):
```
{current_code[:500]}
```""",

        "BATCH": f"""Batch I/O operations in mutable/main.py:

1. Read the current code
2. Find loops that do: database writes, file I/O, HTTP requests, or syscalls one at a time
3. Replace with batch equivalents (bulk insert, batch write,aiohttp, etc.)
4. If no batching available, at minimum collect results and write once
5. Run evaluate.py and print "metric=<value>"

Current code (first 500 chars):
```
{current_code[:500]}
```""",

        "PARALLEL": f"""Parallelize independent work in mutable/main.py:

1. Read the current code
2. Find independent work items that can run concurrently (not dependent on each other's output)
3. Use ThreadPoolExecutor or multiprocessing.Pool to parallelize
4. Ensure thread-safety for shared data
5. Run evaluate.py and print "metric=<value>"

Current code (first 500 chars):
```
{current_code[:500]}
```""",

        "PRECOMPUTE": f"""Precompute values at startup in mutable/main.py:

1. Read the current code
2. Identify computations that use the same data every call but are recomputed each time
3. Move to module-level or __init__ / startup section
4. Run evaluate.py and print "metric=<value>"

Current code (first 500 chars):
```
{current_code[:500]}
```""",

        "COMPILE": f"""Use compiled/native speedups in mutable/main.py:

1. Read the current code
2. Identify Python loops doing numeric computation on large data
3. Try: numpy vectorization, numba @njit, or rewriting hot loop in Cython
4. Fallback if deps are a concern: use built-in functions (sum, map, filter) instead of explicit loops
5. Run evaluate.py and print "metric=<value>"

Current code (first 500 chars):
```
{current_code[:500]}
```""",

        "LAZY": f"""Apply lazy evaluation in mutable/main.py:

1. Read the current code
2. Identify expensive computations done even when results might not be needed
3. Replace eager computation with generators or lazy sequences
4. Use itertools for lazy operations where possible
5. Run evaluate.py and print "metric=<value>"

Current code (first 500 chars):
```
{current_code[:500]}
```""",
    }

    return prompts.get(strategy_name, f"""Apply {strategy_name} to mutable/main.py:
{strategy.get('description', '')}

Current code (first 500 chars):
```
{current_code[:500]}
```

Run evaluate.py and print "metric=<value>".
""")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    project = args.project_dir.resolve()
    mutable = project / "mutable"
    tracker_file = project / ".spec-research-state.json"

    # Load history
    experiments = []
    if tracker_file.exists():
        import json
        state = json.loads(tracker_file.read_text())
        experiments = state.get("experiments", [])

    history_analysis = analyze_history(experiments)
    code_analysis = analyze_code(mutable)

    spec = {}
    tracker_py = project / ".spec-research-state.json"
    if tracker_py.exists():
        import json
        spec = json.loads(tracker_py.read_text()).get("spec", {})

    direction = spec.get("metric_direction", "lower_is_better")
    current_best = None
    if experiments:
        best = max(experiments, key=lambda e: e.get("value") if direction != "lower_is_better" else -e.get("value"))
        current_best = best.get("value")

    strategy = recommend_strategy(history_analysis, code_analysis, current_best, direction)
    prompt = generate_experiment_prompt(
        strategy["strategy"], STRATEGIES.get(strategy["strategy"], {}),
        mutable, spec.get("primary_metric", "score"), direction
    )

    result = {
        "recommendation": strategy,
        "code_analysis": code_analysis,
        "history_analysis": history_analysis,
        "agent_prompt": prompt,
        "strategies_available": list(STRATEGIES.keys()),
    }

    if args.json:
        import json
        print(json.dumps(result, indent=2))
    else:
        print(f"📊 Strategy Recommendation", file=sys.stderr)
        print(f"   Strategy: {strategy['strategy']}", file=sys.stderr)
        print(f"   Confidence: {strategy['confidence']}", file=sys.stderr)
        print(f"   Reason: {strategy['reason']}", file=sys.stderr)
        print(f"\n📈 History: {history_analysis}", file=sys.stderr)
        print(f"\n🔍 Code Analysis: {code_analysis}", file=sys.stderr)
        print(f"\n🤖 Agent Prompt:\n{prompt[:500]}...", file=sys.stderr)


if __name__ == "__main__":
    main()
