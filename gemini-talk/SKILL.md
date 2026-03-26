# gemini-talk —— 与 Google Gemini 网页版对话

> 通过多种方式控制你的 Chrome Tab 中的 Gemini，智能选择传输层，自动沉淀知识到本地知识库。

## 传输层选择（优先级从高到低）

| 方式 | 优先级 | 说明 |
|------|--------|------|
| **opencli** | 1️⃣ 高优 | Chrome 扩展 + 原生桥接，直连网页 Gemini，响应最快，稳定性最高，完全复用登录会话 |
| **web-access** | 2️⃣ 中优 | CDP 直连用户 Chrome，稳定灵活，比 opencli 多一层中转 |
| **OpenClaw 内置 browser** | 3️⃣ 兜底 | 原始方式，当 opencli/web-access 不可用时自动降级使用 |

**优先策略：** 如果 `opencli` 命令存在且扩展已连接，**总是优先使用 opencli**，它效率最高。只有当 opencli 不可用时，才回退到内置 browser。

---

## 核心设计：智能路由

收到用户请求后，四步决策：

```
1. 选择传输层（opencli优先，内置兜底） → 2. 判断复用/新开 → 3. 选择模式（Model） → 4. 选择工具（Tool，可选） → 5. 发送消息
```

---

## Step 1：模式选择

| 模式 | 触发关键词 | 说明 |
|------|-----------|------|
| **快速** | "快速"、"简单"、"一下"、"一句话" | 即时回答，不需要深度 |
| **思考** | "分析"、"解释"、"比较"、"思考"、"为什么" | 复杂推理分析 |
| **Pro 3.1** | "代码"、"编程"、"数学"、"研究"、"深度"、"优化"、"重写" | 高阶任务 |

**选择方式：** 点击"打开模式选择器"(ref=1_23) → 点对应菜单项

---

## Step 2：工具选择

工具菜单通过"工具"按钮(ref=1_22)展开，六种工具：

| 工具 | 触发关键词 | 工具返回值 |
|------|-----------|-----------|
| **制作图片** | "画"、"生成图片"、"image"、"画图" | 返回图片 |
| **Canvas** | "写代码"、"代码"、"编程"、"code"、"可视化" | 可交互代码环境 |
| **Deep Research** | "研究"、"调研"、"research"、"报告" | 深度研究报告 |
| **制作视频** | "视频"、"video"、"动画" | 返回视频 |
| **制作音乐** | "音乐"、"music"、"作曲" | 返回音频 |
| **学习辅导** | "辅导"、"学习"、"作业"、"教我" | 互动学习 |

**选择方式：** 先点"工具"(ref=1_22) → 菜单出现后点对应选项

---

## Step 3：发送消息

**标准流程：**

```
1. snapshot → 找到 textarea(ref) 和发送按钮
2. click textarea (ref=1_18)
3. type 消息
4. snapshot 找到当前可见的发送按钮
5. click 发送按钮
```

**等待回复：** 等 5-8 秒 → snapshot → 读取 `heading "Gemini 说"` 后的 statictext

---

### 会话复用策略（Session-Aware 设计，Gemini Pro 优化版）

采用**多维度判定**代替单纯语义相似度，更鲁棒：

| 判定优先级 | 规则 | 动作 |
|-------------|------|------|
| 1. 时效优先 | 距离上次提问 > 30 分钟 (TTL) | → 直接新开 |
| 2. 指令优先 | 命中 `["换话题", "新对话", "清除上下文", "新开"]` | → 直接新开 |
| 3. LLM 意图判定 | 不满足以上规则 → 构造简短 Prompt 让 Gemini Flash 判定：<br>`"上文话题[{X}]，当前输入[{Y}]，是否同一话题或连续追问？输出 True/False"` | → True 复用 / False 新开 |

**优势：**
- 解决了单纯语义相似度问题："那这个呢" 字面相似度低但实际是连续追问不会误判
- 时间窗口和硬指令优先，减少误判
- LLM 做最终仲裁，准确率更高

### 对话历史沉淀：知识抽取与存储（Gemini Pro 优化版）

当会话结束（触发新开或超时），自动执行**异步 LLM 驱动结构化抽取 + 双库联动**：

```
1. 预读取 DOM → 在刷新前获取完整历史（避免刷新后内容丢失）
2. 清洗 → 过滤语气词、礼貌用语
3. LLM 抽取 → Gemini 自己抽取 JSON 格式三元组
4. 存储 → Chroma 向量 + SQLite 三元组，双向索引
   - Chroma (向量): 存对话 chunk，用于语义检索 RAG
   - SQLite (三元组): 存 (Subject, Predicate, Object)，用于逻辑推理
   - 双向索引: Chroma metadata 存 sqlite_row_id，SQLite 存 vector_id
```

### 存储实现代码

- `libs/knowledge_extractor.py` → 完整实现，支持 LLM 抽取 + 双向索引
- 数据目录: `~/.openclaw/skills/gemini-talk/data/`
  - `chroma/` → Chroma 向量存储
  - `knowledge_triples.db` → SQLite 三元组

#### 使用示例

```python
from libs.knowledge_extractor import KnowledgeBase, async_extract_to_knowledge_base

# 获取 LLM 抽取结果（调用 Gemini 得到 JSON）
llm_extract_result = call_gemini_for_extraction(dialog_text)

# 抽取并存入知识库
result = async_extract_to_knowledge_base(dialog_history, session_id, llm_extract_result)

# 向量检索 + 关联三元组
kb = KnowledgeBase()
results = kb.search_with_triples("gemini-talk pro模式 问题", top_k=3)

# 查询三元组
triples = kb.query_triples(subject="gemini-talk", predicate="preference")
```

---

## GitHub 代码库导入

### 工作流程

```
1. 点击上传菜单 → "导入代码" menuitem
2. 等待"导入代码"对话框出现
3. 在 textbox 中输入 GitHub URL
4. 点击"导入"按钮
5. 等待仓库链接出现（表示导入成功）
6. 在同一输入框中输入分析请求
7. 点击发送
```

### 关键 refs（从 snapshot 获取）
- `上传菜单 → 导入代码(menuitem)` → 触发对话框
- `textbox "GitHub 代码库或分支网址"` → 对话框内输入 ref
- `button "导入"` → 按钮

### 支持的文件上传方式对比

| 方式 | 可用 | 说明 |
|------|------|------|
| **GitHub URL 导入** | ✅ | 最可靠，直接分析仓库代码 |
| **上传文件夹** | ❌ | OS 原生对话框，Playwright 无法控制 |
| **上传文件** | ❌ | OS 原生对话框，Playwright 无法控制 |
| **粘贴内容到 textarea** | ✅ | 读取本地文件 → paste 到输入框 |
| **Google Drive** | 未测试 | 需要 Google 账号授权 |

### 注意
- 导入代码后，仓库文件会作为上下文附加到对话中
- 可以连续发送多条消息，仓库上下文保持有效
- 导入成功后可见 `link "GitHub 图标 xxx GitHub"` 元素

---

### 设计改进：模式状态锁定

针对"发起新对话重置模式"问题，采用了**先选模式，再开新对话 + 懒校验**设计：

```
1. 路由判断 → 锁定模式到 session_context
2. 发起新对话 → 清理历史，保留模式配置
3. 新开对话后懒校验：读取当前页面模式 → 只在不一致时重新选择
```

这样无论开多少次新对话，Pro/think 模式选择都不会丢失，且减少一次 UI 操作降低失败概率。

---

## 完整执行函数

```python
async def gemini_talk(
    message: str,
    force_mode: str = None,
    force_tool: str = None,
    github_url: str = None
):
    """
    message: 用户消息
    force_mode: 可选 "fast"|"think"|"pro" 强制特定模式
    force_tool: 可选 "image"|"canvas"|"deep_research"|"video"|"music"|"tutoring"
    github_url: 可选，GitHub 仓库 URL，自动导入后分析
    """
    # 0. 传输层选择 — opencli 优先，内置兜底
    has_opencli = await check_command_exists("opencli")
    opencli_connected = await check_opencli_connected()
    use_opencli = has_opencli and opencli_connected

    if use_opencli:
        # === 使用 opencli (最高效) ===
        # 切换模式（如果需要）
        if force_mode:
            await opencli_switch_mode(force_mode)
        
        # 通过 opencli 发送消息并获取回复
        response = await opencli_send_chat(message)
        
        # 保存会话上下文（知识沉淀）
        session_context.set("gemini-talk:current_session", {
            "transport": "opencli",
            "history": message + "\n" + response,
            "last_message_time": get_current_timestamp()
        })
        
        return response
    # === 降级到内置 browser ===

    # 0. GitHub 导入路由
    if github_url or (not force_tool and contains_github_url(message)):
        url = github_url or extract_github_url(message)
        question = extract_question_after_url(message)
        return await import_github_and_analyze(url, question)

    # 0. 判断是否复用当前会话（Session-Aware）
    last_session = session_context.get("gemini-talk:current_session", None)
    is_new_topic = intent_router.check_topic_change(
        current_message=message,
        last_context=last_session.history if last_session else None
    )
    
    # 如果需要新开，先抽取旧会话知识到知识库
    if is_new_topic and last_session:
        # 在发起新对话前读取 DOM 历史，避免刷新后丢失
        full_history = get_current_history_from_dom()
        async_extract_to_knowledge_base(full_history, llm_extract=True)
        # 只清除对话历史，保留模式配置
        session_context.clear(keep_keys=["gemini-talk:locked_mode"])
    
    # 1. 模式路由 + 锁定（改进：懒校验，适配 Gemini 最新 UI）
    if force_mode:
        mode = force_mode
    else:
        # 优先从 session 读取已有锁定
        mode = session_context.get("gemini-talk:locked_mode")
        if not mode:
            mode = route_mode(message)
    session_context.set("gemini-talk:locked_mode", mode)
    
    # 2. 如果判定为新主题，发起新对话
    if is_new_topic:
        await click("发起新对话")
        await wait_for_new_chat()
        # ✅ 关键修正：Gemini 最新 UI 中，新开对话一定会重置为快速模式
        # 所以必须在这里重新检测并切换
        current_mode_in_page = get_current_mode_from_page()
        if current_mode_in_page != mode:
            await select_mode(mode)
    
    # 3. 工具路由（默认无工具）
    tool = force_tool or route_tool(message)

    # 4. 选择工具（如果需要）
    if tool:
        await select_tool(tool)

    # 5. 发送消息
    response = await send_message(message)

    # 6. 保存当前会话到上下文
    session_context.set("gemini-talk:current_session", {
        "history": get_current_history(),
        "last_message_time": get_current_timestamp()
    })

    # 7. 读取回复
    return await read_response()
```

### 改进亮点（来自 Gemini Pro review）
1. **减少 UI 操作冗余**：新开对话后只在模式不一致时才切换，降低 Flaky 概率
2. **懒校验模式**：优先复用 session_context 中已锁定的模式
3. **抽取前读取 DOM**：在刷新前读取历史，避免页面刷新导致内容丢失

---

## 模式选择实现

```python
def get_current_mode_from_page() -> str:
    """正确判断当前模式（Gemini UI 反直觉设计）
    Gemini UI 设计：左上角按钮文字 = "你可以点击我切换到这个模式"
    → 如果按钮显示 "PRO"，说明当前不是 PRO，点击才会切换
    → 如果按钮显示 "快速"，说明当前已经是 PRO
    """
    if page_has_button("快速"):
        return "pro"
    elif page_has_button("思考"):
        return "think"
    else:  # 显示 "PRO"
        return "fast"

async def select_mode(mode: str):
    """点击模式选择器，然后选对应模式"""
    await click("打开模式选择器")      # ref=1_23
    await wait_for_menu()
    if mode == "think":
        await click("思考 解决复杂问题") # ref=33_2
    elif mode == "pro":
        await click("Pro 使用 3.1 Pro 处理高阶数学和代码任务") # ref=33_3
    # "fast" 是默认，不需要选
```

## 工具选择实现

```python
async def select_tool(tool: str):
    """点击工具按钮，然后选对应工具"""
    await click("工具")  # ref=1_22
    await wait_for_menu()
    tool_map = {
        "image": "制作图片",
        "canvas": "Canvas",
        "deep_research": "Deep Research",
        "video": "制作视频",
        "music": "制作音乐",
        "tutoring": "学习辅导",
    }
    await click(tool_map[tool])
```

## 消息发送实现

```python
async def send_message(text: str):
    """填入消息并发送"""
    await click("textarea")  # ref=1_18
    await type_text("textarea", text)
    await snapshot()  # 获取当前发送按钮 ref（动态）
    send_ref = find_send_button()
    await click(send_ref)
```

## 回复读取实现

```python
async def read_response():
    """等待生成完成，读取回复内容"""
    await wait_for_generation()
    await snapshot()
    response_text = extract_response_text()
    return response_text
```

---

## 文件上传：GitHub 代码库导入

### 完整流程：GitHub 导入分析

```python
async def import_github_and_analyze(github_url: str, question: str):
    """导入 GitHub 仓库，然后提问"""

    # Step 1: 点击"导入代码"
    await click("打开文件上传菜单")   # ref=1_21
    await snapshot()
    await click("导入代码")           # menuitem ref（动态）
    await wait_for_dialog()

    # Step 2: 输入 GitHub URL
    await type_in("GitHub 代码库或分支网址", github_url)
    await click("导入")               # 按钮

    # Step 3: 等待导入成功（出现 GitHub link）
    await wait_for_condition(
        lambda snap: find_github_link(snap) is not None,
        timeout=15000
    )

    # Step 4: 在 textarea 中输入分析请求
    await click("textarea")
    await type_text("textarea", question)

    # Step 5: 发送
    await snapshot()
    send_ref = find_send_button()
    await click(send_ref)

    # Step 6: 读取回复
    return await read_response()
```

### 设计改进：模式状态锁定

针对"发起新对话重置模式"问题，采用了**先选模式，再开新对话**的设计：

```
1. 路由判断 → 锁定模式到 session_context
2. 发起新对话 → 清理历史，保留模式配置
3. 在新对话中重新选择锁定的模式
```

这样无论开多少次新对话，Pro/think 模式选择都不会丢失。

---

## 错误处理

| 情况 | 处理 |
|------|------|
| 找不到 textarea | 刷新页面重试（用户可能关了 Gemini） |
| 发送按钮 ref 找不到 | 重新 snapshot |
| 超时（90秒无回复） | 返回"生成超时，请重试" |
| 工具选择后页面跳转 | 等待新页面加载完成再填消息 |
| 未登录 | 提示用户先登录 Google 账号 |

---

## 前提条件

- Chrome 已打开 Gemini 并登录（账号：杨洋 yangmail17@163.com）
- **opencli 优先**：opencli 已安装 + Chrome 扩展 opencli Browser Bridge 已加载并连接
  - 检测命令：`opencli doctor` 输出 "Everything looks good!" 即可
- 如果 opencli 不可用，降级到使用 `profile="user"` 内置 browser 连接，不需要扩展
