#!/usr/bin/env python3
"""
discover.py — Codebase Discovery for spec-research

Analyzes a codebase to extract facts that inform the SPEC generation:
- What language(s) / framework(s)
- What the code does (heuristic)
- Where the hot paths likely are (file size, imports)
- Existing test/benchmark infrastructure
- Current metric capture points (print statements, existing benchmarks)

Usage:
    python3 discover.py /path/to/code [--goal "optimization goal"]
"""

import argparse
import ast
import os
import re
import sys
import subprocess
from pathlib import Path
from typing import Optional


LANG_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".sh": "shell",
    ".bash": "shell",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".cs": "csharp",
}


METRIC_PATTERNS = {
    "time": [r"\.perf_counter\(\)", r"time\.time\(\)", r"start\s*=\s*time", r"elapsed\s*="],
    "memory": [r"\.memory_info\(\)", r"psutil", r"tracemalloc", r"resource\.getrusage"],
    "throughput": [r"ops/sec", r"requests/sec", r"items/sec", r"/s"],
    "accuracy": [r"accuracy", r"precision", r"recall", r"f1", r"score"],
}


def find_language(repo: Path) -> str:
    """Detect primary language from file extensions."""
    counts = {}
    for f in repo.rglob("*"):
        if f.is_file() and not any(p in str(f) for p in [".git", "node_modules", "__pycache__", ".venv"]):
            ext = f.suffix.lower()
            lang = LANG_EXTENSIONS.get(ext)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return "unknown"
    return max(counts, key=counts.get)


def find_entry_points(repo: Path, lang: str) -> list[dict]:
    """Find likely entry points (main files, CLI entry points)."""
    candidates = []

    if lang == "python":
        for f in repo.rglob("*.py"):
            content = f.read_text(errors="ignore")
            if any(kw in content for kw in ["if __name__", "argparse", "click", "def main"]):
                candidates.append({"path": str(f.relative_to(repo)), "reason": "entry point"})
        # Also find largest files (likely main logic)
        sizes = [(f.stat().st_size, str(f.relative_to(repo))) for f in repo.rglob("*.py") if f.is_file()]
        for size, path in sorted(sizes, reverse=True)[:3]:
            if not any(c["path"] == path for c in candidates):
                candidates.append({"path": path, "reason": f"large file ({size//1024}KB)"})

    elif lang in ("javascript", "typescript"):
        for f in repo.rglob("*.{js,ts}"):
            content = f.read_text(errors="ignore")
            if any(kw in content for kw in ["require(", "import ", "export ", "async function"]):
                candidates.append({"path": str(f.relative_to(repo)), "reason": "module"})

    return candidates[:5]


def find_metric_capture_points(repo: Path) -> list[dict]:
    """Find existing benchmark/measurement code."""
    findings = []

    for f in repo.rglob("*"):
        if not f.is_file() or f.stat().st_size > 500_000:
            continue
        try:
            content = f.read_text(errors="ignore")
        except Exception:
            continue

        for cat, patterns in METRIC_PATTERNS.items():
            for pat in patterns:
                if pat in content:
                    findings.append({
                        "file": str(f.relative_to(repo)),
                        "category": cat,
                        "pattern": pat,
                        "line_hint": _find_line(content, pat),
                    })
                    break

    return findings[:10]


def _find_line(content: str, pattern: str, context=2) -> str:
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if pattern in line:
            start = max(0, i - context)
            end = min(len(lines), i + context + 1)
            return "\n".join(f"  {j+1}: {lines[j]}" for j in range(start, end))
    return ""


def get_git_info(repo: Path) -> dict:
    """Get git history insights."""
    try:
        r = subprocess.run(
            ["git", "log", "--oneline", "-20"],
            capture_output=True, text=True, cwd=repo, timeout=5
        )
        recent_commits = r.stdout.strip().split("\n") if r.returncode == 0 else []
    except Exception:
        recent_commits = []

    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=repo, timeout=5
        )
        dirty = bool(r.stdout.strip()) if r.returncode == 0 else False
    except Exception:
        dirty = False

    return {"recent_commits": recent_commits, "dirty": dirty}


def summarize_structure(repo: Path) -> list[str]:
    """Get top-level directory structure."""
    try:
        r = subprocess.run(
            ["find", ".", "-maxdepth", "2", "-not", "-path", "./.git*",
             "-not", "-path", "./node_modules*", "-not", "-path", "./__pycache__*",
             "-not", "-path", "./.venv*", "-type", "f",
             "-name", "*.*", "-printf", "%f\n"],
            capture_output=True, text=True, cwd=repo, timeout=5
        )
        files = sorted(set(r.stdout.strip().split("\n"))) if r.returncode == 0 else []
        dirs = sorted(set(p.parent for p in repo.rglob("*") if p.is_dir()
                    and ".git" not in str(p) and "node_modules" not in str(p)
                    and "__pycache__" not in str(p)))[:8]
        return [f"📁 {d.relative_to(repo)}/" for d in dirs]
    except Exception:
        return []


def generate_discovery_report(repo: Path, goal: Optional[str] = None) -> str:
    """Generate a discovery report as markdown."""
    lang = find_language(repo)
    entry_points = find_entry_points(repo, lang)
    metric_points = find_metric_capture_points(repo)
    git_info = get_git_info(repo)
    structure = summarize_structure(repo)

    report = f"""# Discovery Report — {repo.name}

> Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}
> Goal: {goal or '(not specified)'}

## Language & Stack

- **Primary language:** {lang}
- **Repository root:** {repo.resolve()}

## Code Structure

```
"""
    for s in structure:
        report += f"{s}\n"

    report += """```

## Entry Points

"""
    if entry_points:
        for ep in entry_points:
            report += f"- `{ep['path']}` — {ep['reason']}\n"
    else:
        report += "_None found_\n"

    report += """
## Existing Metric Capture

"""
    if metric_points:
        for mp in metric_points:
            report += f"""### {mp['category']} — `{mp['file']}`
```
{mp['line_hint'] or mp['pattern']}
```

"""
    else:
        report += "_No obvious benchmark/measurement code found_\n"

    report += """
## Git Status

"""
    if git_info["dirty"]:
        report += "⚠️ Working tree is dirty (uncommitted changes)\n"
    else:
        report += "✅ Working tree is clean\n"

    report += """
## Recent Commits

"""
    if git_info["recent_commits"]:
        for c in git_info["recent_commits"][:5]:
            report += f"- `{c}`\n"
    else:
        report += "_No git history_\n"

    report += f"""
## Discovery Notes

"""
    # Auto-generate some heuristic notes
    if lang == "python":
        report += "- Python project detected — `time.perf_counter()` is the standard timing approach\n"
        report += "- Consider adding `tracemalloc` for memory profiling\n"
        if entry_points:
            report += f"- Target file: likely `{entry_points[0]['path']}`\n"

    if metric_points:
        cats = set(mp['category'] for mp in metric_points)
        report += f"- Existing metrics: {', '.join(cats)}\n"

    report += """
---

*Generated by spec-research discover.py*
"""
    return report


def main():
    parser = argparse.ArgumentParser(description="Codebase discovery for spec-research")
    parser.add_argument("path", type=Path, help="Code directory to analyze")
    parser.add_argument("--goal", help="Optional goal hint (e.g., 'make it faster')")
    parser.add_argument("--output", "-o", type=Path, help="Save report to file")
    args = parser.parse_args()

    repo = args.path.resolve()
    if not repo.is_dir():
        print(f"Error: {repo} is not a directory", file=sys.stderr)
        sys.exit(1)

    print(f"🔍 Discovering {repo}...", file=sys.stderr)
    report = generate_discovery_report(repo, args.goal)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report)
        print(f"✅ Discovery report saved to {args.output}", file=sys.stderr)
    else:
        print(report)

    # Also print the path to the report file for the calling agent
    return report


if __name__ == "__main__":
    main()
