# yyaa-skills

分享一些好用的 OpenClaw 自定义技能。

## 已收录技能

| 技能 | 说明 |
|------|------|
| skill-install-guide | 第三方技能安装排障指南 |
| spec-research | AI 原生代码性能优化技能 — 接受自然语言优化目标，生成正式规范（SPEC.md），在 git 分支上自主运行实验循环，直到目标达成或搜索空间耗尽 |

## 安装方式

将技能目录复制到 `~/.openclaw/skills/` 即可。

```bash
# 方式一：直接复制
cp -r skill-install-guide ~/.openclaw/skills/

# 方式二：克隆本仓库
git clone https://github.com/YYaa18/yyaa-skills.git ~/.openclaw/skills/
```

## spec-research 技能说明

### 核心设计
- **目标**：让 AI 作为"研究工程师"，接受自然语言优化目标，生成正式规范（SPEC.md），在 git 分支上自主运行实验，直到目标达成
- **工作流**：Discover → Spec → Plan → Experiment Loop → Evaluate（循环）
- **核心原则**："If it can't be measured, it can't be improved"；一次实验一个变量；好结果合并，坏结果丢弃

### 关键组件
- `autoinit.py` — 初始化项目，从自然语言目标创建 SPEC.md、evaluate.py（测量脚本）
- `discover.py` — 分析代码库，检测语言、入口点、现有性能测量点
- `run_loop.py` — 实验循环，支持分支隔离 + Web 仪表板（localhost:19842）
- `strategy_advisor.py` — 分析实验历史+代码模式，推荐下一个策略
- `experiment_tracker.py` — 持久化状态管理

### 架构演进
新版（v2）已转向 **Supervisor-Worker 架构**，废弃外部脚本流水线，改用 OpenClaw Sub-Agent 原生 ReAct 循环。见 [SKILL.md](spec-research/SKILL.md)。

## 来源

本仓库仅用于备份和分享，技能由 [ClawX](https://github.com/YYaa18) 创建和维护。
