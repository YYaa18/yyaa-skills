# gemini-talk — 与 Google Gemini 网页版对话

> 通过 OpenClaw browser 工具直接控制你的 Chrome Tab，智能选择模式和工具。

## 核心设计：智能路由

收到用户请求后，三步决策：

```
1. 选择模式（Model） → 2. 选择工具（Tool，可选） → 3. 发送消息
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
    # 0. GitHub 导入路由
    if github_url or (not force_tool and contains_github_url(message)):
        url = github_url or extract_github_url(message)
        question = extract_question_after_url(message)
        return await import_github_and_analyze(url, question)

    # 1. 模式路由（默认 think）
    mode = force_mode or route_mode(message)

    # 2. 工具路由（默认无工具）
    tool = force_tool or route_tool(message)

    # 3. 选择模式
    if mode != "fast":  # fast 是默认，无需选择
        await select_mode(mode)

    # 4. 选择工具（如果需要）
    if tool:
        await select_tool(tool)

    # 5. 发送消息
    await send_message(message)

    # 6. 读取回复
    return await read_response()
```

---

## 模式选择实现

```python
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
    """读取 Gemini 的回复"""
    # 等待"继续生成"按钮出现（流式输出完毕）
    while True:
        await wait(3000)
        snap = await snapshot()
        if has_continue_button(snap):
            await click_continue()
        if has_response(snap):
            break
    return extract_text(snap, after_heading="Gemini 说")
```

---

## 智能路由规则

### 模式路由
```
if any(k in msg for k in ["代码", "编程", "函数", "class ", "def "]):
    → pro
elif any(k in msg for k in ["分析", "为什么", "解释", "比较", "思考"]):
    → think
else:
    → fast
```

### 工具路由
```
if any(k in msg for k in ["画", "生成图片", "image", "画图"]):
    → image
elif any(k in msg for k in ["深度研究", "调研", "research", "行业报告"]):
    → deep_research
elif any(k in msg for k in ["写代码", "编程", "code", "可视化", "交互"]):
    → canvas
elif any(k in msg for k in ["视频", "动画"]):
    → video
elif any(k in msg for k in ["音乐", "作曲"]):
    → music
elif any(k in msg for k in ["辅导", "教我", "学习", "作业"]):
    → tutoring
else:
    → no tool
```

### 文件上传路由
```
if contains_github_url(msg) or any(k in msg for k in ["代码库", "仓库", "repo", "import github"]):
    → github_import
elif any(k in msg for k in ["上传文件", "上传文件夹", "attach"]):
    → file_upload
elif any(k in msg for k in ["粘贴", "复制内容"]):
    → paste_content
else:
    → no upload
```

---

## 文件上传：GitHub 代码库导入

Gemini 支持直接导入 GitHub 仓库分析，是最可靠的上传方式。

### 触发关键词
- "分析 XX 代码库"
- "导入 GitHub"
- "看看这个仓库"
- GitHub URL

### 执行流程

```
1. 打开上传菜单 → 点击"导入代码"菜单项
2. 等待"导入代码"对话框出现
3. 在 textbox 中输入 GitHub URL
4. 点击"导入"按钮
5. 等待仓库链接出现（表示导入成功）
6. 在同一输入框中输入分析请求
7. 点击发送
```

### 关键 refs（从 snapshot 获取）
- `上传菜单 → 导入代码(menuitem)` → 触发对话框
- `textbox "GitHub 代码库或分支网址"` → ref=51_4（对话框内）
- `button "导入"` → ref=51_6
- 导入成功后出现 `link "GitHub 图标 XXX GitHub"` → 表示已挂载

### 代码实现

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
- 使用 `profile="user"` 连接，不需要任何扩展
- targetId 从 `browser(action="tabs", profile="user")` 获取，通常是 "1"
