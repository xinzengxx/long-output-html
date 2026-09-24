---
name: long-output-html
description: Use when the answer will likely exceed three terminal paragraphs or the user asks for a detailed/structured explanation. Decide before writing正文, render the full answer to local HTML first, then reply in the terminal with only a brief conclusion, 3-7 bullet summaries, and the HTML path.
---

# long-output-html

将长回答直接渲染成一本「绿墨印刷编辑部」气质的本地 HTML 页面，而不是先在终端输出长正文再二次改写。

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
4. **统一走现有脚本**：只调用安装好的 `render_long_output_html.py`（默认安装于 `~/.claude/scripts/`）。
5. **只描述当前能力**：不要假设折叠、搜索或其他未实现交互。

## 视觉基准（绿墨印刷编辑部）

- **全局配色**：绿墨底 `#33452f` × 奶油米文字 `#ece2cb`，宋体 Black（Songti SC 900）做展示级标题，PingFang 做正文；强调即奶油本身，不再引入第二色相。
- **页面结构即印刷品**：绿底封面（对位线 ✚、幽灵字水印、放射扇、版画枝叶、印章「注」、竖排标签）→ 米字阅读区 → 满版米纸插页（引文）→ 绿色要点区 → 米纸尾声（「完」印）。所有颜色变化处使用撕纸边（SVG），绿↔绿之间连续无痕。
- **尺度跳差**：封面 84px 展示体大标 + 21px 宋体 standfirst；章节开场 = 左栏 104px 大数字 + 「壹贰叁」中文数字小印 kicker + 44px 标题，跳差 ≥4×。
- **正文纪律**：42em 版心全部模块同宽对齐；段落两端对齐 + 首行缩进 2 字符；章节首段自动首字下沉；重点词自动着重点（`text-emphasis`）；正文永远静止不参与入场动画。
- **模块语法**：`body`（正文 + 章末注卡）、`summary`（要点三栏 + 幽灵数字）、`quote`（满版米纸插页 + 双层内框 + 幽灵引号 + 「印」）、`compare`（双卡 + 竖排「对照」+ ■ 结论行）、`figure`（米纸图版，tick-rows 刻线图）。
- **米纸插页与图版**是仅有的反色时刻；表格自动挂「表版 · N SPECIMEN TABLE」标签，图版自动挂「图版 · N FIGURE」。
- **动效 = 印刷车间**：分节线划出 + 菱形线珠、章节大数字上版、印章砸落、满版滚墨擦入、刻线逐根排上、顶部阅读进度线。全部为 CSS scroll-driven 动画，只用 transform/opacity/clip-path，正文不参与；`prefers-reduced-motion` 与不支持的浏览器直接呈现完成态。
- **可访问性**：正文对比度 ≥6:1，次级文字 ≥4.5:1；装饰层全部 `aria-hidden`；图版带 `role="img"` 中文摘要；打印样式强制白纸深字并隐藏装饰层。
- 外部依赖克制：字体全部系统回退，MathJax 仅在内容含公式时加载，pygments 可用且代码块有语言标注时自动高亮（限定在深色代码板内）。

## 最小输入结构

在调用本 skill 前，先把内容组织成 JSON：

```json
{
  "title": "页面标题",
  "subtitle": "副标题，可选",
  "summary": ["3-7 条导读"],
  "sections": [
    {"title": "一级栏目标题", "content": "栏目正文，支持 Markdown 多段"}
  ],
  "appendix": ["附录内容，可选"],
  "output": "/tmp/claude-long-output-<timestamp>.html"
}
```

字段约束：
- `title`：必填；含逗号/分号的短标题会自动在标点后断行
- `summary`：建议填写，3-7 条最佳（渲染为「导读」区）
- `sections`：必填，正文主体
- `appendix` / `output`：可选

## 增强输入结构（可选）

```json
{
  "theme": "green",
  "tags": ["EDITORIAL", "TYPOGRAPHY"],
  "body_variant": "narrative",
  "sections": ["..."]
}
```

### 顶层可选字段

- `theme`: `"green"`（默认，绿墨底米字）| `"paper"`（米色底绿字，正文底色反转；封面保持绿底品牌版式，插页反转为绿底）
- `tags`: 封面右缘竖排标签
- `body_variant`: `"narrative" | "sidenotes"`（sidenotes 时注卡折叠在章节底部）
- `math`: 含公式时自动探测，也可显式 `true`
- `seal`: 封面印章字，默认取标题首字

### section 类型

- `type: "body"`（默认）：`title` + 可选 `kicker` + 可选 `lead` + `content`（Markdown）+ 可选 `notes[]`（章末注卡，`{"label","content"}`）
- `type: "summary"`：`title` + `items[{"title","text"}]`，渲染为三栏要点 + 幽灵数字
- `type: "quote"`：满版米纸引文插页；`content`（可用换行分行）、`note`、`attribution`、`kicker`（默认「引文」）
- `type: "compare"`：`left{title,items}` / `right{title,items}`（item 为 `{"label","text"}`）+ `takeaway`
- `type: "figure"`：米纸图版，tick-rows 刻线图
  - `title`：结论式标题（如「跳差从 1.9× 拉开到 5.2×」），不要写「柱状图」
  - `sub`：图例与单位说明；`source`：来源行
  - `unit_step`: 每根刻线的单位（默认 0.1）
  - `rows[{"label","value","display"}]`：`value` 按单位换算刻线数，`display` 为行尾标注；可选 `hero: true` 强调主角行
  - 1 tick = `unit_step`，刻线数上限 70；数据必须从零起算，禁止断轴

## 推荐使用方式

- 把页面看成「统一视觉语汇下的多模块长文系统」：导读定脉络 → body 主叙述（穿插 figure 图版）→ quote 满版停顿 → summary/compare 收束。
- 图版用于「有真实数据支撑的对比/尺度/计数」；没有数据就不要硬造 figure。
- 每一节建议给一个 2-6 字的 `kicker`（如「问题的定位」），它会被盖上一枚中文数字小印。

## 生成前检查清单

- 终端分诊是否已经决定走 HTML？正文栏是否 42em、约 40 字每行？
- section 标题 + kicker 是否已足够表达结构？没有数据是否避免了 figure？
- 引文是否真的值得一次满版停顿？（一页至多 1-2 处）
- 主题选择：默认 green；需要纸面阅读感时才用 paper。
- 是否只承诺当前脚本已实现的能力？

## 执行步骤

1. 先完成长度分诊，确认走 HTML。
2. 将内容组织为上述 JSON。
3. 使用 Bash 调用：

```bash
python3 "<安装路径>/render_long_output_html.py" <<'EOF'
<JSON>
EOF
```

4. 记录脚本返回的真实 HTML 路径。
5. 在终端只输出：一句话结论、3-7 条核心摘要、HTML 路径、可选一句阅读建议。

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

HTML 路径：
- /tmp/claude-long-output-20260925-153000-a1b2c3.html
```

## 失败处理

如果 HTML 渲染脚本失败：

1. 简短告知用户“HTML 渲染失败”
2. 说明失败点（例如 JSON 格式问题 / 脚本调用失败）
3. 优先修正渲染问题后重新生成
4. 不要退回到直接在终端铺完整长正文，除非用户明确要求
