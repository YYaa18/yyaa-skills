# openSpec — Research Specification Format

The openSpec format is a **specification-first**驱动 research protocol.
Every spec-research project starts with a SPEC.md generated from a natural-language goal.

---

## openSpec v1.0

```markdown
# SPEC.md — {project-name}

> Generated: {YYYY-MM-DD HH:MM} · spec-research autoinit

## 1. Goal

Clear, concrete statement of WHAT to optimize.
One goal per project. No ambiguity.

## 2. Metrics

| # | Metric | Direction | Measurement | Target Delta |
|---|--------|-----------|-------------|--------------|
| ★ | {primary} | {higher/lower} is better | {how to measure} | ≥ {N}% |

**Primary metric:** {metric_name}
**Secondary metrics:** {optional list}

## 3. Baseline

```bash
# Commands to establish baseline
$ python3 fixed/evaluate.py
metric={baseline_value}
```

Baseline: **{baseline_value}**

## 4. Experiment Loop

- **Budget per experiment:** {N seconds/minutes}
- **Max experiments:** {N}
- **Mutable file(s):** `{paths}`
- **Forbidden:** `fixed/` dir, new deps without approval

## 5. Success Criteria

Research is **done** when ANY:
- Primary metric improved ≥ {N}% vs baseline
- Secondary metrics within ±{M}% AND primary improved
- {max} experiments exhausted

Research is **stopped** when:
- No improvement after {patience} consecutive experiments
- Metric regresses significantly (>50% worse)

## 6. Evaluation Script (fixed/evaluate.py)

```python
# MUST print "metric={float}" to stdout
# MUST be deterministic (no random variation in metric)
# MUST complete within budget
```

## 7. Constraints

1. `fixed/` directory: NEVER modified by experiment loop
2. Each experiment = 1 git commit (hash tracked in results.tsv)
3. If regressed: `git reset --hard` before next experiment
4. No dependency additions without explicit approval
5. Metric must be measurable in isolation

## 8. Results Log

```tsv
commit  metric  value   delta   status  description
abc123  latency 0.0421  -0.0012 improve baseline
def456  latency 0.0403  -0.0030 improve switch to heap
```

---

## Key Design Principles

### Spec-First
Every research project MUST have a SPEC.md before any experiment runs.
The spec is the contract between goal and execution.

### Metric-Driven
If you can't measure it, you can't improve it.
Every metric must be:
- **Objective**: reproducible by anyone
- **Isolated**: not affected by external factors
- **Timely**: completes within budget

### Fail Fast
If 5 consecutive experiments show no improvement → stop and reassess.
Don't run 100 experiments if the 5th already proves the approach is dead.

### Delta Over Absolute
Always compare against baseline, not absolute numbers.
`delta = current - baseline` tells the true story.

### Git as Lab Notebook
Every experiment is a commit. Good or bad.
`git log --oneline` is your experiment history.
`git reset --hard` is your "discard bad result" button.

---

## Common Patterns

### Pattern 1: Speed Optimization
```
Goal: Make X N times faster
Metric: latency/throughput (lower is better)
Baseline: Measure original
Strategy: Profile → Optimize hot path → Measure → Repeat
```

### Pattern 2: Accuracy Improvement
```
Goal: Improve accuracy of X by N%
Metric: accuracy (higher is better)
Baseline: Current accuracy %
Strategy: Error analysis → Fix frequent failure modes → Measure → Repeat
```

### Pattern 3: Size Reduction
```
Goal: Reduce size of X by N%
Metric: file_size/lines (lower is better)
Baseline: Current size
Strategy: Remove unused code → Simplify → Measure → Repeat
```

---

## Anti-Patterns

❌ **Vague goals**: "make it better" → SPEC can't be written
❌ **Multiple metrics**: Pick ONE primary. Others are secondary/constraints.
❌ **Unmeasurable**: If you can't print "metric=N", the spec is incomplete
❌ **No baseline**: Running experiments without baseline = no comparison
❌ **Infinite loop**: Always set max_experiments and success criteria upfront
