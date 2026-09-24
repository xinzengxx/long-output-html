# long-output-html

把 Claude 的长回答直接渲染成本地 HTML 页面阅读，而不是先把长正文铺满终端。

这个仓库包含三部分：

- `skills/long-output-html/SKILL.md`：skill 定义
- `scripts/render_long_output_html.py`：把结构化 JSON 渲染成 HTML，并写入 sidecar/stamp
- `scripts/open_long_output_if_fresh.sh`：供 Claude Code `Stop` hook 调用，在回答结束后自动打开刚生成的 HTML

当前默认方案按你本地 Claude 目录安装，目标是尽量复用现有闭环，不引入额外依赖或额外服务。

## 效果

- 当回答预计超过三段时，优先走 HTML 阅读
- 终端只保留一句结论、3–7 条摘要和 HTML 路径
- HTML 写到本地临时文件
- 若配置了 `Stop` hook，Claude 回复结束后会自动打开最新 HTML

## 设计系统：绿墨印刷编辑部

页面被当作一件「手工印刷品」来排版，而不是一篇网页文章：

- **绿墨底 × 奶油米字**：`#33452f` 底 + `#ece2cb` 文字，宋体 Black 展示标题 + PingFang 正文，正文对比度 ≥6:1
- **绿底封面**：印刷对位线 ✚、幽灵字水印、放射扇、版画枝叶、印章「注」（取标题首字）、竖排标签
- **尺度跳差**：章节开场 = 104px 大数字 + 「壹贰叁」中文数字小印 + 44px 标题
- **正文纪律**：42em 版心全模块同宽、两端对齐 + 首行缩进 2 字符、首字下沉、着重号
- **模块**：`body`（+ 章末注卡）、`summary` 三栏要点、`quote` 满版米纸插页、`compare` 对照卡、`figure` 米纸图版（tick-rows 刻线图，骨架来自 [lieflat-charts](https://github.com/larashero3-dotcom/lieflat-charts)）
- **撕纸边**：所有颜色变化处使用 SVG 撕纸转场，绿↔绿之间连续无痕
- **印刷车间动效**：分节线划出、数字上版、印章砸落、满版滚墨、刻线排上——全部为 CSS scroll-driven 动画（零 JS 依赖），`prefers-reduced-motion` 与旧浏览器直接呈现完成态
- **可访问性**：正文对比度 ≥6:1、次级 ≥4.5:1，装饰层 `aria-hidden`，图版带中文 `aria-label`，打印强制白纸深字
- **双主题**：`green`（默认，绿墨底米字）/ `paper`（米色底绿字；封面保持绿底，插页反转为绿底）

## 当前边界

- 自动打开脚本当前使用 macOS 的 `open` 命令，因此默认只验证过 macOS
- Linux / Windows 用户如果需要自动打开，请自行替换 `open_long_output_if_fresh.sh` 里的打开命令
- 如果你只想要 HTML 渲染，不需要自动打开，可以只安装 skill 和 render 脚本，不配置 `Stop` hook

## 安装

### 1. 复制 skill

将仓库里的 skill 目录复制到 Claude 目录：

```bash
mkdir -p ~/.claude/skills
cp -R skills/long-output-html ~/.claude/skills/
```

### 2. 复制脚本

```bash
mkdir -p ~/.claude/scripts
cp scripts/render_long_output_html.py ~/.claude/scripts/
cp scripts/open_long_output_if_fresh.sh ~/.claude/scripts/
chmod +x ~/.claude/scripts/render_long_output_html.py
chmod +x ~/.claude/scripts/open_long_output_if_fresh.sh
```

### 3. 配置 `Stop` hook

把 `settings/settings.example.json` 里的 `hooks.Stop` 示例合并到你的 `~/.claude/settings.json`。

最小示例：

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$HOME/.claude/scripts/open_long_output_if_fresh.sh\" \"/tmp/claude-last-html-path.txt\" \"/tmp/claude-long-output.stamp\""
          }
        ]
      }
    ]
  }
}
```

如果你已有其他 `Stop` hooks，请合并，不要直接覆盖整个 `settings.json`。

## 使用方式

### 方式 1：作为 skill 使用

当你需要详细、结构化、明显超过三段的回答时，使用 `/long-output-html`。

该 skill 的约束是：

- 必须在正文输出前决定走不走 HTML
- 不先在终端铺长正文，再事后改成 HTML
- 终端只输出简短结论、摘要和 HTML 路径

### 方式 2：直接调用渲染脚本

你也可以直接传入 JSON：

```bash
python3 $HOME/.claude/scripts/render_long_output_html.py <<'EOF'
{
  "title": "示例长回答",
  "subtitle": "最小渲染测试",
  "summary": [
    "这是第一条摘要",
    "这是第二条摘要",
    "这是第三条摘要"
  ],
  "sections": [
    {
      "title": "正文示例",
      "content": "第一段内容。\n\n第二段内容。"
    }
  ]
}
EOF
```

脚本会：

- 生成一个本地 HTML 文件
- 写入 `/tmp/claude-last-html-path.txt`
- 写入 `/tmp/claude-long-output.stamp`
- 在 stdout 输出最终 HTML 路径

## 模块化排版能力

当前渲染脚本在保留旧 JSON 兼容性的前提下，支持更细的 section 级排版控制。

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

#### `narrative`

适合连续解释、系统分析、章节式长文主体，视觉上更接近宽松双栏的编辑排版。

#### `sidenotes`

适合主正文 + 注释栏的长文，右侧显示定义、补充说明、术语解释。

注意：如果 `notes` 为空，脚本会自动退回 `narrative`，避免出现空边栏。

### 模块混排示例

下面这个 JSON 会在同一篇长文里混排不同 section：

```json
{
  "title": "模块化长文示例",
  "subtitle": "不同小节可以使用不同排版形式",
  "summary": [
    "第一节用 narrative。",
    "第二节用 sidenotes。",
    "后面再插入对比和引用模块。"
  ],
  "body_variant": "narrative",
  "sections": [
    {
      "type": "body",
      "variant": "narrative",
      "title": "第一节：背景铺垫",
      "lead": "这节用纯叙述型正文。",
      "content": "第一段正文。\n\n第二段正文。"
    },
    {
      "type": "body",
      "variant": "sidenotes",
      "title": "第二节：概念解释",
      "lead": "这节用主正文 + 边注栏。",
      "content": "这里是主叙述。\n\n继续展开解释。",
      "notes": [
        {"label": "术语", "content": "这里是边注解释。"},
        {"label": "提示", "content": "没有足够旁注时应退回 narrative。"}
      ]
    },
    {
      "type": "compare",
      "title": "第三节：方案对比",
      "left": {
        "title": "方案 A",
        "items": [
          {"label": "优点", "text": "实现简单"}
        ]
      },
      "right": {
        "title": "方案 B",
        "items": [
          {"label": "优点", "text": "表达更丰富"}
        ]
      },
      "takeaway": "不同 section 可以按内容角色切换版式。"
    },
    {
      "type": "quote",
      "content": "先按内容角色分块，再按块选版式。",
      "note": "这是整个系统的核心设计原则。"
    }
  ]
}
```

上面这个示例说明的是：

- 一篇长文里可以有多个 section
- 每个 section 的形式可以不同
- 混排粒度是 `sections[]`
- 目前不是“同一个 section 内部再切不同正文版式”，而是“不同 section 之间混排”

## 验证

建议按下面顺序验收：

### A. 渲染链路

执行上面的最小 JSON 示例，确认：

- 返回了一个 `.html` 路径
- 该 HTML 文件确实存在
- `/tmp/claude-last-html-path.txt` 已写入最新 HTML 路径
- `/tmp/claude-long-output.stamp` 已生成

### B. 自动打开链路

手动运行：

```bash
bash $HOME/.claude/scripts/open_long_output_if_fresh.sh \
  /tmp/claude-last-html-path.txt \
  /tmp/claude-long-output.stamp
```

确认：

- 浏览器或系统默认 HTML 查看器被打开
- `/tmp/claude-long-output.stamp` 被消费删除

### C. 真实 skill 链路

在 Claude Code 里触发一次 `/long-output-html`，确认：

- 终端只保留简短摘要，不重复全文
- 输出了 HTML 路径
- 回答结束后自动打开 HTML（若已配置 `Stop` hook）

## 仓库结构

```text
.
├── README.md
├── LICENSE
├── skills/
│   └── long-output-html/
│       └── SKILL.md
├── scripts/
│   ├── render_long_output_html.py
│   └── open_long_output_if_fresh.sh
└── settings/
    └── settings.example.json
```

## 设计说明

这个仓库刻意保持最小化：

- 不公开个人 `settings.local.json`
- 不携带无关 permission allowlist
- 不打包其他 hooks 或个人脚本
- 不扩展未验证的新交互能力

发布版只保留当前已验证可用的最小闭环。

## License

MIT
