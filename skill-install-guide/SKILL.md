---
name: skill-install-guide
description: OpenClaw 第三方技能安装排障指南 — 记录真实安装痛点及解决方案
metadata: {"openclaw":{"emoji":"🔧","category":"meta"}}
---

# Skill Install Guide — 第三方技能安装排障手册

本文档基于真实安装经验编写，持续更新。

---

## 痛点一：Skill 文件藏在嵌套目录里

**现象：** 从 GitHub 克隆的仓库，SKILL.md 不在根目录，而是在 `skills/skill-name/` 子目录下。

**案例：** `tclawde/coding-agent` 仓库结构是 `skills/coding-agent/SKILL.md`，直接克隆到 `~/.openclaw/skills/` 会导致路径错误。

**解决：**
```bash
# 找到真正的 skill 文件
find . -name "SKILL.md" -path "*/skills/*" 2>/dev/null

# 提取到正确位置（以 coding-agent 为例）
SKILL_NAME="coding-agent"
TARGET="$HOME/.openclaw/skills/$SKILL_NAME"
mkdir -p "$TARGET"
# 假设 SKILL.md 在 skills/coding-agent/ 子目录
mv "skills/$SKILL_NAME/SKILL.md" "$TARGET/SKILL.md"
mv "skills/$SKILL_NAME/README.md" "$TARGET/README.md"

# 清理多余的嵌套 skills 目录和其他垃圾文件
rm -rf "skills/" ".github/" "node_modules/" "*.py" "*.json" "*.js" "*.scpt" 2>/dev/null
```

---

## 痛点二：GitHub Release 的 ZIP 不完整

**现象：** 下载的扩展包（Chrome Extension 等）解压后缺少关键文件（如 `dist/background.js`），导致扩展无法加载。

**案例：** `jackwener/opencli` 的 `opencli-extension.zip` 缺少构建产物，但源码中有完整的 `extension/dist/`。

**解决：**
```bash
# 方案A：从源码构建（适用于 Node.js 项目）
git clone --depth 1 https://github.com/USERNAME/REPO.git /tmp/repo-build
cd /tmp/repo-build/extension
npm install
npm run build  # 或 vite build / esbuild 等
# 将构建产物复制到目标位置
cp -r dist ~/Desktop/EXTENSION_NAME/

# 方案B：直接用源码（如果构建产物已存在于源码中）
cp -r /tmp/repo-build/extension ~/Desktop/EXTENSION_NAME/
```

---

## 痛点三：Skill 路径硬编码了 ~/.claude

**现象：** 技能文件中引用了 `~/.claude/skills`、`$CLAUDE_SKILL_DIR` 等路径，在 OpenClaw 环境下不生效。

**案例：** `eze-is/web-access` 技能原始路径适配来自 Claude Code 环境。

**解决：**
```bash
# 批量替换技能目录中的路径
SKILL_DIR="$HOME/.openclaw/skills/skill-name"
# 替换 ~/.claude → ~/.openclaw
sed -i '' "s|/Users/YOUR_USER/.claude|/Users/YOUR_USER/.openclaw|g" "$SKILL_DIR"/*.md "$SKILL_DIR"/*.sh 2>/dev/null
# 替换环境变量
sed -i '' "s|\$CLAUDE_SKILL_DIR|\$OPENCLAW_SKILL_DIR|g" "$SKILL_DIR"/*.md 2>/dev/null
sed -i '' "s|\$CLAUDE_PROJECT_DIR|\$OPENCLAW_WORKSPACE|g" "$SKILL_DIR"/*.md 2>/dev/null
```

---

## 痛点四：npm 全局包安装后 command not found

**现象：** `npm install -g` 成功，但终端里找不到命令。

**原因：** Node.js 版本过低（要求 >= 20），或 npm 全局路径未加入 PATH。

**解决：**
```bash
# 检查 Node 版本
node --version  # 需要 >= 20.0.0

# 查找 npm 全局路径
npm bin -g  # 通常是 /usr/local/bin 或 ~/.npm-global/bin

# 确认 PATH 包含 npm 全局 bin
echo $PATH | tr ':' '\n' | grep npm
```

---

## 痛点五：Chrome Extension 加载失败（Manifest V3 问题）

**现象：** Chrome 扩展加载后报错"无法加载背景脚本"或"无法加载清单"。

**常见原因：**
1. ZIP 包不完整（见痛点二）
2. `manifest_version: 3` 但 `background.service_worker` 指向不存在的文件
3. 扩展目录中 `manifest.json` 引用了 `dist/` 下的文件但 `dist/` 不存在

**解决：**
```bash
# 检查 manifest.json 的 background 配置
cat ~/Desktop/EXTENSION/manifest.json | python3 -c "
import sys, json
m = json.load(sys.stdin)
bg = m.get('background', {})
print('service_worker:', bg.get('service_worker'))
print('type:', bg.get('type'))
"

# 确认 dist 文件存在
ls ~/Desktop/EXTENSION/dist/ 2>/dev/null || echo "dist/ 目录不存在，需要构建"

# 如果是预发布版但 dist 已存在于源码中
git clone --depth 1 https://github.com/USERNAME/REPO.git /tmp/ext-src
cp -r /tmp/ext-src/extension/dist ~/Desktop/EXTENSION/
```

---

## 痛点六：Skill 安装后 gateway 不识别

**现象：** 技能文件存在，但 `openclaw skills list` 中看不到。

**原因：** `SKILL.md` 的 `metadata.openclaw.requires` 字段声明了依赖工具（如 `claude`），但该工具不存在或路径不在 PATH 中。

**解决：**
```bash
# 检查技能是否被识别
openclaw skills list | grep skill-name

# 检查 SKILL.md metadata
cat <<'EOF'
---
name: skill-name
description: ...
metadata: {"openclaw":{"emoji":"🔧","requires":{"anyBins":["cmd1","cmd2"]}}}
---
EOF

# 验证依赖工具是否存在
which cmd1 cmd2
```

---

## 安装后必做清单

- [ ] `ls ~/.openclaw/skills/SKILL_NAME/SKILL.md` 文件存在
- [ ] `openclaw skills list | grep SKILL_NAME` 能看到该技能
- [ ] 技能文档中的路径已正确适配（无 `~/.claude` 残留）
- [ ] 依赖工具已安装且在 PATH 中
- [ ] 功能测试通过（如 `opencli doctor` / `claude --version` 等）

---

## 快速诊断脚本

运行以下命令快速定位安装问题：

```bash
openclaw skills list  # 列出所有已安装技能
ls ~/.openclaw/skills/  # 检查技能目录结构
which <skill-binary>  # 验证依赖工具
opencli doctor 2>&1 | head -10  # 验证 opencli 类工具
cat ~/.openclaw/skills/<name>/SKILL.md | head -5  # 确认 metadata 完整
```
