---
name: long-output-html
description: Use when the answer will likely exceed three terminal paragraphs or the user asks for a detailed/structured explanation. Decide before writing正文, render the full answer to local HTML first, then reply in the terminal with only a brief conclusion, 3-7 bullet summaries, and the HTML path.
---

# long-output-html

将长回答直接渲染到本地 HTML 页面，而不是先在终端输出长正文再二次改写。

## 何时必须使用

满足任一条件时，直接走本 skill：

- 预计回答不能在三段内讲清
- 用户要求“详细介绍 / 详细分析 / 系统讲讲 / 展开说说 / 全面对比”
- 预计需要明显的章节结构，终端直接展开会降低可读性
- 不确定会不会超长时，默认走 HTML

## 核心规则

1. **先分诊，后输出**：必须在正文输出前决定是否走 HTML。
2. **禁止事后补救**：不要先在终端铺长正文，再改成 HTML。
3. **终端只留摘要**：生成 HTML 后，终端只输出一句话结论、3-7 条摘要、HTML 路径、可选一句阅读建议。
4. **统一走现有脚本**：只调用 `/Users/xinyuan/.claude/scripts/render_long_output_html.py`。
5. **只描述当前能力**：不要假设折叠、标签展示或其他未实现交互。

## 视觉基准

- 目标是轻量的 editorial reading page：清楚、克制、适合长文阅读，而不是重型前端页面。
- 标题层级要稳定：页面标题负责定调，section 标题负责分段，正文内标题只承担局部层级。
- `summary` 更像导读栏，`quote` 更像杂志 pull quote，`compare` 更像左右编辑对照卡。
- 保持少装饰、多留白、单一强调色；避免复杂动画、重阴影、炫技渐变和未实现的交互承诺。

## 最小输入结构

在调用本 skill 前，先把内容组织成 JSON：

```json
{
  "title": "页面标题",
  "subtitle": "副标题，可选",
  "summary": ["3-7 条摘要"],
  "sections": [
    {
      "title": "一级栏目标题",
      "content": "栏目正文，支持多段"
    }
  ],
  "appendix": ["附录内容，可选"],
  "output": "/tmp/claude-long-output-<timestamp>.html"
}
```

字段约束：
- `title`：必填
- `summary`：建议填写，3-7 条最佳
- `sections`：必填，正文主体
- `subtitle` / `appendix` / `output`：可选
- 若不传 `output`，脚本会自动生成唯一 HTML 文件名

## 增强输入结构（可选）

当前脚本已经支持模块化排版；在不破坏旧输入的前提下，可以额外传以下字段：

```json
{
  "title": "页面标题",
  "subtitle": "副标题",
  "summary": ["导读 1", "导读 2", "导读 3"],
  "body_variant": "narrative",
  "tags": ["editorial", "longform"],
  "sections": [
    {
      "type": "body",
      "variant": "narrative",
      "title": "章节标题",
      "lead": "章节导语，可选",
      "content": "多段正文 Markdown"
    },
    {
      "type": "quote",
      "content": "一句需要被强调的话",
      "note": "补充解释，可选",
      "attribution": "署名，可选"
    },
    {
      "type": "summary",
      "title": "本节要点",
      "items": [
        {"title": "要点一", "text": "一句解释"},
        {"title": "要点二", "text": "一句解释"}
      ]
    },
    {
      "type": "compare",
      "title": "方案对比",
      "left": {
        "title": "方案 A",
        "items": [
          {"label": "优点", "text": "稳定"}
        ]
      },
      "right": {
        "title": "方案 B",
        "items": [
          {"label": "风险", "text": "更复杂"}
        ]
      },
      "takeaway": "一句总结，可选"
    }
  ]
}
```

### 顶层可选字段

- `body_variant`: `"narrative" | "sidenotes"`
  - 控制正文模块的默认主版式
  - 默认值为 `"narrative"`
- `tags`: 页面顶部标签列表，可选

### section 可选字段

- `type`: `"body" | "summary" | "quote" | "compare"`
  - 不传时默认按 `body` 处理
- `variant`: `"narrative" | "sidenotes"`
  - 仅对 `type: "body"` 生效
  - 不传时继承顶层 `body_variant`
- `lead`: 正文章节导语，可选
- `notes`: 仅对 `variant: "sidenotes"` 生效
  - 支持字符串数组：`["注释 1", "注释 2"]`
  - 也支持对象数组：`[{"label": "术语", "content": "解释"}]`

### 两种正文主版式

#### 1. `narrative`
用于纯叙述型长文，视觉上更接近宽松双栏的编辑排版。

适合：
- 连续解释
- 系统分析
- 章节式长文主体

不适合：
- 需要大量旁注、术语解释、补充上下文的内容

#### 2. `sidenotes`
用于主正文 + 旁注栏的长文，右侧展示注释、定义、补充说明。

适合：
- 概念解释型内容
- 方法论文章
- 带术语定义、补充背景的长文

注意：
- 如果 `notes` 为空，脚本会自动退回 `narrative`
- 当前是静态阅读版式，不提供复杂折叠交互

## 推荐使用方式

建议把页面看成“统一视觉语汇下的多模块长文系统”：

- `summary`：顶部导读摘要
- `body + narrative`：主叙述
- `body + sidenotes`：主叙述 + 注释栏
- `quote`：节奏停顿与关键观点强调
- `compare`：并列分析与对照说明

也就是说：
- **正文主版式只保留 narrative / sidenotes 两类**
- 标题、摘要、引用、对比更适合作为插入模块，而不是再定义成新的主页面模板

## 示例 1：叙述型长文

```json
{
  "title": "注意力不是稀缺资源，而是排版问题",
  "subtitle": "用模块化长文重新组织阅读节奏",
  "summary": [
    "先定内容角色，再选版式。",
    "正文主版式只保留两类。",
    "引用和对比作为插入模块更稳。"
  ],
  "body_variant": "narrative",
  "sections": [
    {
      "type": "body",
      "title": "为什么旧版长文容易显得单调",
      "lead": "问题不在于颜色太少，而在于所有内容都被迫进入同一个排版壳。",
      "content": "第一段正文。\n\n第二段正文。\n\n第三段正文。"
    },
    {
      "type": "quote",
      "content": "先建立模块语法，再做视觉变化。",
      "note": "这样更适合后续自动分块与稳定套模板。"
    },
    {
      "type": "compare",
      "title": "旧方式 vs 新方式",
      "left": {
        "title": "单一模板",
        "items": [
          {"label": "优点", "text": "实现简单"},
          {"label": "缺点", "text": "长文容易疲劳"}
        ]
      },
      "right": {
        "title": "模块化模板",
        "items": [
          {"label": "优点", "text": "节奏更清楚"},
          {"label": "成本", "text": "需要更明确的 schema"}
        ]
      }
    }
  ]
}
```

## 示例 2：边注型长文

```json
{
  "title": "把解释写进边栏，而不是塞进正文",
  "subtitle": "边注型长文适合知识增强式阅读",
  "body_variant": "sidenotes",
  "sections": [
    {
      "type": "body",
      "variant": "sidenotes",
      "title": "主叙述与次级语义层要分开",
      "lead": "边注的价值不是多一栏，而是让次级信息和主叙述脱耦。",
      "content": "第一段正文。\n\n第二段正文。\n\n第三段正文。",
      "notes": [
        {"label": "术语", "content": "次级语义层指不影响主线理解、但会增强理解的补充信息。"},
        {"label": "提示", "content": "如果没有足够注释材料，就不要强行做边注型。"}
      ]
    }
  ]
}
```

## 执行步骤

1. 先完成长度分诊，确认走 HTML。
2. 将内容组织为上述 JSON。
3. 使用 Bash 调用：

```bash
python3 "/Users/xinyuan/.claude/scripts/render_long_output_html.py" <<'EOF'
<JSON>
EOF
```

4. 记录脚本返回的真实 HTML 路径。
5. 在终端只输出：
   - 一句话结论
   - 3-7 条核心摘要
   - HTML 路径
   - 可选一句阅读建议

## 与 hook 的关系

- 渲染脚本会写出 HTML 文件，并更新 sidecar 与 stamp
- Stop hook 会在回答结束后尝试自动打开刚生成的 HTML
- 是否走长输出，必须由回答前的长度分诊决定，不依赖 hook 判断

## 输出约束

终端不要重复 HTML 正文，只输出类似：

```text
一句话结论：这是一个适合 HTML 阅读的长回答。

核心摘要：
- ...
- ...
- ...

HTML 路径：
- /tmp/claude-long-output-20260401-153000.html
```

## 失败处理

如果 HTML 渲染脚本失败：

1. 简短告知用户“HTML 渲染失败”
2. 说明失败点（例如 JSON 格式问题 / 脚本调用失败）
3. 优先修正渲染问题后重新生成
4. 不要退回到直接在终端铺完整长正文，除非用户明确要求
