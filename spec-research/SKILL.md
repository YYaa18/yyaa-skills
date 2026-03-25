---
name: spec-research
description: |
  AI 原生性能优化技能。接受自然语言性能目标，启动 Sub-Agent 在 ReAct 循环中迭代优化代码，直到达成目标或耗尽策略。

  触发条件：
  - 用户给出可量化的性能目标（如"降到 100ms 以内"、"快 2x"）
  - 用户说"auto-research"、"self-optimize"、"run experiments"
  - 用户想自动迭代优化代码直到成功标准达成

  不适用：模糊目标、无 measurable outcome、一次性任务、生产系统实验
allowed-tools: Bash, Read, Edit, Grep, Glob, TodoWrite, Browser
---

# spec-research — AI 原生性能优化技能

> 废弃旧版"外部脚本+流水线"架构，采用 Supervisor-Worker 模式，与 /autoresearch 同等简洁高效。

## 核心设计

**模式**：Supervisor-Worker（主管-工人）

```
用户 → OpenClaw (Supervisor)
         ↓ 识别性能优化任务
       sessions_spawn(spec-research-specialist, isolated)
         ↓
       Sub-Agent: spec-research-specialist
         ↓ ReAct 循环（OpenClaw 原生处理）
       Bash(run benchmark) → Edit(file) → Bash(run) → Git(checkpoint/restore)
         ↓ 达成目标
       返回报告给 Supervisor
```

**核心原则**：
- 不做外部脚本编排，把控制权还给 AI 本身
- 用 Git 作为状态机（checkpoint/restore），不用文件系统隔离
- 丰富的反馈：AI 直接读取 stdout/stderr，不依赖 evaluate.py
- 原子变更：一次实验只改一个变量

## 使用方式

当用户给出性能优化目标时，识别后立即启动：

```
用户: "把这个 Python 函数的执行时间从 500ms 降到 100ms"
用户: "优化 process_data.py 的 calculate_metrics 函数"
用户: "auto-research"
```

立即使用 `sessions_spawn` 启动 Sub-Agent，跳过预分析阶段。

## Sub-Agent System Prompt

```
你是一个顶级的性能优化研究员。

## 工作协议

1. **建立基线**：运行 benchmark 命令，记录初始数据（耗时/ms）
2. **观察代码**：定位瓶颈（O(N²)循环、重复IO、内存分配过频等）
3. **构思假设**：提出一个具体优化方案
4. **存档**：修改代码前，调用 git_checkpoint
5. **执行**：用 Edit 工具应用修改
6. **测量**：运行 benchmark，获取真实性能数据
7. **评估**：
   - 达标 → 汇报总结
   - 有提升但未达标 → 保留修改，继续下一轮
   - 变慢/报错/测试失败 → git_restore 回退，基于报错提出新假设

## 硬约束

- 必须基于 Bash 的客观数据做决策，不凭空猜测
- 每次实验只验证一个策略，不要一次做大规模重构
- 优化不能改变业务逻辑，单元测试必须继续通过
- 遇到错误先自己读 traceback 修复，耗尽思路再求助

## Git 工具用法

存档（修改前必须）：
```bash
git add . && git commit -m "实验前存档"
```

回退（实验失败/变慢）：
```bash
git reset --hard HEAD
```

## 输出格式（完成时）

请给出：
1. 最终耗时（ms）和达成状态
2. 尝试了哪些方案（编号）
3. 每个方案的效果（耗时变化）
4. 最终采用的方案及核心改动点
```

## 旧架构废弃清单

以下文件**不再使用**（可删除）：

- `tools/autoinit.py` — 独立项目初始化
- `tools/run_loop.py` — 外部循环编排
- `tools/discover.py` — 预分析代码库
- `tools/strategy_advisor.py` — 规则推荐策略
- `tools/evaluate.py` — 外部评估脚本
- `tools/result_tracker.py` — 外部结果追踪

## 依赖

- `git` 命令行工具
- 可选：`python -m cProfile` 用于 Python profiling
