#!/usr/bin/env python3
import html
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

import mistune

DEFAULT_OUTPUT_DIR = "/tmp"
DEFAULT_OUTPUT_PREFIX = "claude-long-output"
DEFAULT_STAMP = "/tmp/claude-long-output.stamp"
DEFAULT_SIDECAR = "/tmp/claude-last-html-path.txt"
SUPPORTED_SECTION_TYPES = {"body", "summary", "quote", "compare"}
SUPPORTED_BODY_VARIANTS = {"narrative", "sidenotes"}


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def markdown_to_html(text: str) -> str:
    if not text:
        return ""
    renderer = mistune.create_markdown(
        escape=False,
        plugins=["strikethrough", "table", "task_lists", "footnotes"],
    )
    return renderer(str(text).strip())


def list_items(items, class_name="summary-list"):
    if not items:
        return ""
    lis = "\n".join(f"<li>{esc(x)}</li>" for x in items if str(x).strip())
    return f'<ul class="{class_name}">{lis}</ul>' if lis else ""


def tag_html(tags):
    if not tags:
        return ""
    chips = "".join(
        f'<span class="tag">{esc(tag)}</span>' for tag in tags if str(tag).strip()
    )
    return f'<div class="tag-row">{chips}</div>' if chips else ""


def reading_meta(raw_content: str):
    word_count = len(re.sub(r"\s+", "", raw_content or ""))
    read_time = max(1, word_count // 300) if word_count else 1
    return word_count, read_time


def normalize_body_variant(value, default="narrative"):
    variant = str(value or default).strip().lower()
    if variant not in SUPPORTED_BODY_VARIANTS:
        return default
    return variant


def normalize_section(section, default_variant):
    normalized = dict(section or {})
    section_type = str(normalized.get("type") or "body").strip().lower()
    if section_type not in SUPPORTED_SECTION_TYPES:
        section_type = "body"
    normalized["type"] = section_type
    if section_type == "body":
        normalized["variant"] = normalize_body_variant(
            normalized.get("variant"), default_variant
        )
    return normalized


def normalize_notes(notes):
    normalized = []
    for note in notes or []:
        if isinstance(note, dict):
            label = str(note.get("label") or "").strip()
            content = str(note.get("content") or note.get("text") or "").strip()
            if label or content:
                normalized.append({"label": label, "content": content})
        else:
            content = str(note).strip()
            if content:
                normalized.append({"label": "", "content": content})
    return normalized


def normalize_text_items(section):
    items = section.get("items") or section.get("points") or []
    normalized = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                title = str(item.get("title") or "").strip()
                text = str(item.get("text") or item.get("content") or "").strip()
                if title or text:
                    normalized.append({"title": title, "text": text})
            else:
                text = str(item).strip()
                if text:
                    normalized.append({"title": "", "text": text})
    if normalized:
        return normalized

    raw_content = str(section.get("content") or "").strip()
    if not raw_content:
        return []

    for line in raw_content.splitlines():
        cleaned = re.sub(r"^[-*0-9.\s]+", "", line).strip()
        if cleaned:
            normalized.append({"title": "", "text": cleaned})
    return normalized


def normalize_compare_side(side, fallback_title):
    if isinstance(side, dict):
        title = str(side.get("title") or fallback_title).strip()
        items = side.get("items") or side.get("points") or []
    else:
        title = fallback_title
        items = side or []

    normalized_items = []
    for item in items:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("title") or "").strip()
            text = str(item.get("text") or item.get("content") or "").strip()
            if label or text:
                normalized_items.append({"label": label, "text": text})
        else:
            text = str(item).strip()
            if text:
                normalized_items.append({"label": "", "text": text})

    return {"title": title, "items": normalized_items}


def render_section_kicker(section, index, prefix="SECTION"):
    explicit = str(section.get("kicker") or "").strip()
    if explicit:
        return f'<div class="section-kicker">{esc(explicit)}</div>'

    sequence = str(section.get("sequence") or "").strip()
    if sequence:
        label = str(section.get("sequence_label") or prefix).strip()
        return f'<div class="section-kicker">{esc(label)} {esc(sequence)}</div>'

    if section.get("numbered") is True:
        label = str(section.get("sequence_label") or prefix).strip()
        return f'<div class="section-kicker">{esc(label)} {index:02d}</div>'

    return ""


def render_body_section(section, index):
    title = esc(section.get("title", "未命名栏目"))
    lead = str(section.get("lead") or "").strip()
    raw_content = str(section.get("content") or "")
    body = markdown_to_html(raw_content)
    word_count, read_time = reading_meta(raw_content)
    variant = section.get("variant", "narrative")
    notes = normalize_notes(section.get("notes"))
    if variant == "sidenotes" and not notes:
        variant = "narrative"

    kicker_html = render_section_kicker(section, index)
    header = f"""
    <header class=\"section-header\">
      {kicker_html}
      <h2 class=\"section-title\">{title}</h2>
      {f'<p class="section-lead">{esc(lead)}</p>' if lead else ''}
      <div class=\"section-meta\">
        <span class=\"meta-item\">约 {read_time} 分钟</span>
        <span class=\"meta-dot\">•</span>
        <span class=\"meta-item\">{word_count} 字符</span>
      </div>
    </header>
    """

    if variant == "sidenotes":
        notes_html = "".join(
            f"""
            <article class=\"note-item\">
              {f'<div class="note-label">{esc(note["label"])}</div>' if note['label'] else ''}
              <div class=\"note-body\">{markdown_to_html(note['content'])}</div>
            </article>
            """
            for note in notes
        )
        layout = f"""
        <div class=\"body-layout body-layout-sidenotes\">
          <div class=\"article-body\">{body}</div>
          <aside class=\"notes-rail\">
            <div class=\"notes-heading\">旁注</div>
            <div class=\"notes-list\">{notes_html}</div>
          </aside>
        </div>
        """
    else:
        layout = f"""
        <div class=\"body-layout body-layout-narrative\">
          <div class=\"article-body narrative-body\">{body}</div>
        </div>
        """

    return f"""
    <article class=\"module module-body module-body-{variant}\" id=\"sec-{index}\">
      {header}
      {layout}
    </article>
    """


def render_summary_section(section, index):
    title = esc(section.get("title") or "重点摘要")
    intro = str(section.get("intro") or section.get("lead") or "").strip()
    items = normalize_text_items(section)
    items_html = "".join(
        f"""
        <li class=\"summary-card\">
          <div class=\"summary-index\">•</div>
          <div class=\"summary-copy\">
            {f'<h3 class="summary-card-title">{esc(item["title"])}</h3>' if item['title'] else ''}
            <p class=\"summary-card-text\">{esc(item['text'])}</p>
          </div>
        </li>
        """
        for i, item in enumerate(items, start=1)
    )
    kicker_html = render_section_kicker(section, index, "摘要")
    return f"""
    <section class=\"module module-summary\" id=\"sec-{index}\">
      <header class=\"module-header\">
        {kicker_html}
        <h2 class=\"module-title\">{title}</h2>
        {f'<p class="module-intro">{esc(intro)}</p>' if intro else ''}
      </header>
      <ol class=\"summary-cards\">{items_html}</ol>
    </section>
    """


def render_quote_section(section, index):
    quote = str(section.get("quote") or section.get("content") or "").strip()
    note = str(section.get("note") or section.get("caption") or "").strip()
    attribution = str(section.get("attribution") or "").strip()
    return f"""
    <aside class=\"module module-quote\" id=\"sec-{index}\">
      <div class=\"quote-rule\"></div>
      <blockquote class=\"quote-main\">
        <p class=\"quote-mark\">“</p>
        <p class=\"quote-text\">{esc(quote)}</p>
      </blockquote>
      {f'<p class="quote-note">{esc(note)}</p>' if note else ''}
      {f'<p class="quote-attribution">— {esc(attribution)}</p>' if attribution else ''}
      <div class=\"quote-rule\"></div>
    </aside>
    """


def render_compare_items(items):
    return "".join(
        f"""
        <li class=\"compare-item\">
          {f'<span class="compare-label">{esc(item["label"])}</span>' if item['label'] else ''}
          <span class=\"compare-text\">{esc(item['text'])}</span>
        </li>
        """
        for item in items
    )


def render_compare_section(section, index):
    title = esc(section.get("title") or "对比")
    left = normalize_compare_side(section.get("left"), "方案 A")
    right = normalize_compare_side(section.get("right"), "方案 B")
    takeaway = str(section.get("takeaway") or "").strip()
    kicker_html = render_section_kicker(section, index, "对照")
    return f"""
    <section class=\"module module-compare\" id=\"sec-{index}\">
      <header class=\"module-header\">
        {kicker_html}
        <h2 class=\"module-title\">{title}</h2>
      </header>
      <div class=\"compare-grid\">
        <article class=\"compare-card\">
          <div class=\"compare-card-title\">{esc(left['title'])}</div>
          <ul class=\"compare-list\">{render_compare_items(left['items'])}</ul>
        </article>
        <div class=\"compare-divider\">对照</div>
        <article class=\"compare-card\">
          <div class=\"compare-card-title\">{esc(right['title'])}</div>
          <ul class=\"compare-list\">{render_compare_items(right['items'])}</ul>
        </article>
      </div>
      {f'<p class="compare-takeaway">{esc(takeaway)}</p>' if takeaway else ''}
    </section>
    """


def render_module(section, index, default_variant):
    normalized = normalize_section(section, default_variant)
    section_type = normalized["type"]
    if section_type == "summary":
        return render_summary_section(normalized, index)
    if section_type == "quote":
        return render_quote_section(normalized, index)
    if section_type == "compare":
        return render_compare_section(normalized, index)
    return render_body_section(normalized, index)


def build_default_output_path() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    return str(Path(DEFAULT_OUTPUT_DIR) / f"{DEFAULT_OUTPUT_PREFIX}-{timestamp}-{suffix}.html")


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        raise SystemExit("Expected JSON on stdin")
    data = json.loads(raw)

    title = data.get("title", "Claude 长输出")
    subtitle = data.get("subtitle", "")
    summary = data.get("summary", [])
    sections = data.get("sections", [])
    appendix = data.get("appendix", [])
    tags = data.get("tags", [])
    body_variant = normalize_body_variant(data.get("body_variant"), "narrative")
    output = data.get("output") or build_default_output_path()
    stamp = data.get("stamp", DEFAULT_STAMP)
    sidecar = data.get("sidecar", DEFAULT_SIDECAR)
    generated_at = data.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M")

    try:
        dt = datetime.strptime(generated_at, "%Y-%m-%d %H:%M")
        display_date = dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        display_date = str(generated_at)

    if appendix:
        sections = list(sections) + [
            {"title": "附录 / 技术细节", "content": "\n\n".join(appendix), "type": "body"}
        ]

    raw_search = "\n".join(
        [str(title), str(subtitle), "\n".join(str(x) for x in summary or [])]
        + [str(section.get("content") or section.get("quote") or "") for section in sections]
        + [str(x) for x in appendix or []]
    )
    math_enabled = bool(data.get("math")) or bool(
        re.search(r"\$\$|\\\(|\\\)|\\\[|\\\]|\\begin\{", raw_search)
    )
    mathjax_html = (
        """
  <script>
    window.MathJax = {
      tex: {
        inlineMath: [['$','$'], ['\\\\(','\\\\)']],
        displayMath: [['$$','$$'], ['\\\\[','\\\\]']],
        processEscapes: true,
        processEnvironments: true,
        tags: 'ams'
      },
      svg: {
        fontCache: 'global',
        scale: 1,
        minScale: 0.5,
        linebreaks: { automatic: false },
        mtextInheritFont: true,
        merrorInheritFont: true
      },
      options: {
        skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
      }
    };
  </script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
"""
        if math_enabled
        else ""
    )

    subtitle_html = f'<div class="subtitle">{esc(subtitle)}</div>' if subtitle else ""
    summary_html = (
        f"""
    <section class=\"lead-section\">
      <div class=\"eyebrow\">导读摘要</div>
      <div class=\"lead-list\">{list_items(summary)}</div>
    </section>
    """
        if summary
        else ""
    )

    html_doc = f"""<!doctype html>
<html lang=\"zh-CN\" data-theme=\"light\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>{esc(title)}</title>
  <style>
    :root {{
      --font-serif: "Songti SC", "STSong", "Noto Serif CJK SC", "Source Han Serif SC", Georgia, serif;
      --font-body: "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", sans-serif;
      --font-sans: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      --font-mono: "JetBrainsMono Nerd Font", "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      --page-width: 1080px;
      --reading-width: 70ch;
      --reading-size: clamp(1.02rem, 0.96rem + 0.22vw, 1.12rem);
    }}

    :root[data-theme=\"light\"] {{
      --bg: #f5f1e6;
      --surface: rgba(255, 252, 246, 0.62);
      --ink: #2d2926;
      --ink-soft: #6f665f;
      --rule-strong: #292522;
      --rule-soft: #d8ccbc;
      --accent: #b26a3d;
      --accent-text: #8a4d2d;
      --accent-soft: rgba(178, 106, 61, 0.12);
      --code-bg: #e8e0d3;
      --progress: #b26a3d;
      --shadow: 0 20px 50px rgba(61, 48, 36, 0.06);
    }}

    :root[data-theme=\"dark\"] {{
      --bg: #1f1b18;
      --surface: rgba(35, 31, 28, 0.8);
      --ink: #ded6cc;
      --ink-soft: #9f9489;
      --rule-strong: #d2c7bb;
      --rule-soft: #4a433c;
      --accent: #d7a27c;
      --accent-text: #e1b18f;
      --accent-soft: rgba(215, 162, 124, 0.14);
      --code-bg: #2c2722;
      --progress: #d7a27c;
      --shadow: none;
    }}

    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; scroll-behavior: smooth; }}
    body {{
      font-family: var(--font-body);
      background:
        radial-gradient(circle at 20% -10%, color-mix(in srgb, var(--accent-soft) 52%, transparent), transparent 34rem),
        linear-gradient(180deg, color-mix(in srgb, var(--bg) 92%, #fff 8%), var(--bg));
      color: var(--ink);
      padding: 48px 20px 104px;
      transition: background-color 0.4s ease, color 0.4s ease;
      text-rendering: optimizeLegibility;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
      font-kerning: normal;
      font-variant-east-asian: proportional-width;
    }}

    #reading-progress {{
      position: fixed;
      top: 0;
      left: 0;
      height: 3px;
      width: 100%;
      background: var(--progress);
      z-index: 1001;
      transform: scaleX(0);
      transform-origin: left center;
      transition: transform 0.15s ease-out;
    }}

    .theme-toggle {{
      position: fixed;
      right: 30px;
      bottom: 30px;
      width: 44px;
      height: 44px;
      border: 1px solid var(--rule-soft);
      border-radius: 50%;
      background: var(--surface);
      color: var(--ink-soft);
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      z-index: 1000;
      opacity: 0.55;
      transition: opacity 0.2s ease, color 0.2s ease, border-color 0.2s ease, background-color 0.2s ease;
      box-shadow: var(--shadow);
      backdrop-filter: blur(8px);
    }}
    .theme-toggle:hover {{ opacity: 1; color: var(--ink); border-color: var(--ink-soft); }}
    .theme-toggle:focus-visible {{
      outline: 2px solid var(--accent-text);
      outline-offset: 4px;
      opacity: 1;
    }}
    .theme-toggle svg {{ width: 20px; height: 20px; }}
    :root[data-theme=\"light\"] .icon-sun {{ display: none; }}
    :root[data-theme=\"light\"] .icon-moon {{ display: block; }}
    :root[data-theme=\"dark\"] .icon-sun {{ display: block; }}
    :root[data-theme=\"dark\"] .icon-moon {{ display: none; }}

    .document-shell {{
      width: min(var(--page-width), 100%);
      margin: 0 auto;
    }}

    .masthead {{
      max-width: 920px;
      border-bottom: 1px solid var(--rule-soft);
      padding: 0 0 42px;
      margin-bottom: 38px;
    }}
    .masthead-meta {{
      margin-bottom: 20px;
      color: var(--ink-soft);
      font-family: var(--font-sans);
      font-size: 0.78rem;
      line-height: 1.7;
      letter-spacing: 0.03em;
    }}
    .masthead h1 {{
      max-width: 860px;
      margin: 0;
      font-family: var(--font-serif);
      font-size: clamp(2.35rem, 5.3vw, 4.75rem);
      font-weight: 700;
      line-height: 1.08;
      letter-spacing: -0.055em;
      color: var(--ink);
      text-wrap: balance;
    }}
    .subtitle {{
      margin: 22px 0 0;
      max-width: 760px;
      font-size: clamp(1.08rem, 0.98rem + 0.35vw, 1.28rem);
      line-height: 1.9;
      letter-spacing: 0.01em;
      color: var(--ink-soft);
    }}
    .tag-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }}
    .tag {{
      padding: 6px 10px;
      border: 1px solid var(--rule-soft);
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--ink-soft);
      font-family: var(--font-sans);
      font-size: 0.74rem;
      line-height: 1.4;
      letter-spacing: 0.02em;
    }}

    .eyebrow, .section-kicker, .notes-heading, .compare-card-title, .note-label, .summary-index {{
      font-family: var(--font-sans);
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      color: var(--accent-text);
    }}

    .lead-section {{
      max-width: 880px;
      padding: 24px 0 38px;
      margin-bottom: 56px;
      border-bottom: 1px solid var(--rule-soft);
    }}
    .eyebrow {{
      display: inline-block;
      margin-bottom: 18px;
      padding-bottom: 4px;
      border-bottom: 1px solid var(--rule-soft);
    }}
    .lead-list {{
      max-width: 82ch;
    }}
    .summary-list {{
      margin: 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 10px;
    }}
    .summary-list li {{
      position: relative;
      margin: 0;
      padding: 13px 16px 13px 28px;
      border-left: 2px solid color-mix(in srgb, var(--accent) 58%, transparent);
      background: color-mix(in srgb, var(--surface) 76%, transparent);
      font-size: 1rem;
      line-height: 1.82;
      letter-spacing: 0.01em;
    }}
    .summary-list li::before {{
      content: "";
      position: absolute;
      left: 13px;
      top: 1.62em;
      width: 4px;
      height: 4px;
      border-radius: 50%;
      background: var(--accent-text);
    }}

    .articles-container {{ display: grid; gap: 72px; }}
    .module {{
      padding-bottom: 72px;
      border-bottom: 1px solid var(--rule-soft);
    }}
    .module:last-child {{ border-bottom: none; padding-bottom: 0; }}
    .module-header, .section-header {{ margin-bottom: 28px; }}
    .section-kicker {{ margin-bottom: 10px; }}
    .module-title, .section-title {{
      max-width: 820px;
      margin: 0;
      font-family: var(--font-serif);
      font-size: clamp(1.9rem, 3.6vw, 3.25rem);
      font-weight: 650;
      line-height: 1.16;
      letter-spacing: -0.045em;
      text-wrap: balance;
    }}
    .module-intro, .section-lead {{
      max-width: 760px;
      margin: 18px 0 0;
      font-size: 1.02rem;
      line-height: 1.92;
      letter-spacing: 0.01em;
      color: var(--ink-soft);
    }}
    .section-meta {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 16px;
      color: var(--ink-soft);
      font-family: var(--font-sans);
      font-size: 0.72rem;
      letter-spacing: 0.03em;
    }}
    .meta-dot {{ color: var(--rule-soft); }}

    .body-layout {{ display: grid; gap: 32px; }}
    .body-layout-narrative {{ gap: 24px; }}
    .body-layout-sidenotes {{
      grid-template-columns: minmax(0, 2.2fr) minmax(230px, 0.85fr);
      gap: 44px;
      align-items: start;
    }}
    .article-body {{
      font-family: var(--font-body);
      font-size: var(--reading-size);
      line-height: 2.05;
      color: var(--ink);
      letter-spacing: 0.015em;
      word-break: break-word;
      overflow-wrap: anywhere;
      hanging-punctuation: allow-end;
    }}
    .article-body.narrative-body {{
      max-width: var(--reading-width);
    }}
    .article-body p {{
      margin: 0 0 1.55em;
      text-align: start;
    }}
    .article-body p + p {{ margin-top: -0.18em; }}
    .article-body h1, .article-body h2, .article-body h3, .article-body h4, .article-body h5, .article-body h6 {{
      max-width: 32em;
      margin: 2.2em 0 0.82em;
      font-family: var(--font-serif);
      line-height: 1.34;
      font-weight: 650;
      letter-spacing: -0.026em;
      color: var(--ink);
      text-wrap: balance;
    }}
    .article-body h1 {{ font-size: clamp(1.58rem, 1.18rem + 1.1vw, 2.1rem); }}
    .article-body h2 {{ font-size: clamp(1.36rem, 1.08rem + 0.72vw, 1.72rem); }}
    .article-body h3 {{ font-size: 1.18rem; color: var(--ink); }}
    .article-body h4 {{ font-size: 1.04rem; color: var(--ink-soft); }}
    .article-body hr {{ border: none; border-top: 1px solid var(--rule-soft); margin: 2.4em 0; }}
    .article-body a {{ color: var(--accent-text); text-decoration: none; border-bottom: 1px solid color-mix(in srgb, var(--accent) 42%, transparent); }}
    .article-body a:hover {{ border-bottom-color: var(--accent); }}
    .article-body strong {{ font-weight: 700; color: color-mix(in srgb, var(--ink) 88%, var(--accent-text)); }}
    .article-body em {{ font-style: normal; color: var(--accent-text); }}
    .article-body blockquote {{
      margin: 34px 0;
      padding: 20px 24px 20px 26px;
      border-left: 3px solid var(--accent);
      background: color-mix(in srgb, var(--accent-soft) 54%, transparent);
      color: var(--ink);
      font-size: 1.05rem;
      line-height: 1.9;
    }}
    .article-body blockquote p {{ margin-bottom: 0.9em; }}
    .article-body blockquote p:last-child {{ margin-bottom: 0; }}
    .article-body ul, .article-body ol {{
      margin: 0 0 1.75em;
      padding-left: 1.35em;
    }}
    .article-body li {{
      margin-bottom: 0.68em;
      padding-left: 0.16em;
    }}
    .article-body li::marker {{ color: var(--accent-text); }}
    .article-body table {{ width: 100%; border-collapse: collapse; margin: 2em 0; font-size: 0.94em; line-height: 1.72; }}
    .article-body th, .article-body td {{ border: 1px solid var(--rule-soft); padding: 11px 13px; vertical-align: top; }}
    .article-body th {{ background: color-mix(in srgb, var(--code-bg) 72%, transparent); text-align: left; font-weight: 700; }}
    .article-body img {{ max-width: 100%; height: auto; display: block; margin: 1.7em auto; }}
    code, pre {{ font-family: var(--font-mono); font-size: 0.9em; }}
    code {{ background: var(--code-bg); padding: 0.16em 0.38em; border-radius: 5px; }}
    pre {{ background: var(--code-bg); padding: 18px 20px; border-radius: 10px; overflow-x: auto; margin: 0 0 1.85em; line-height: 1.68; border: 1px solid color-mix(in srgb, var(--rule-soft) 72%, transparent); }}
    mjx-container {{
      color: var(--ink);
      font-size: 1.02em;
      line-height: 1.35;
    }}
    mjx-container[jax="SVG"][display="true"] {{
      display: block;
      max-width: 100%;
      margin: 1.35em 0;
      padding: 0.35em 0;
      overflow-x: auto;
      overflow-y: hidden;
      white-space: nowrap;
    }}
    mjx-container[jax="SVG"][display="true"] svg {{
      display: block;
      margin: 0 auto;
      max-width: none;
    }}
    mjx-container[jax="SVG"] > svg {{
      vertical-align: -0.16em;
    }}
    .article-body.narrative-body mjx-container[jax="SVG"][display="true"] {{
      column-span: all;
      -webkit-column-span: all;
    }}

    .notes-rail {{
      border-top: 1px solid var(--rule-soft);
      padding-top: 18px;
      position: sticky;
      top: 28px;
    }}
    .notes-heading {{ margin-bottom: 16px; }}
    .notes-list {{ display: grid; gap: 16px; }}
    .note-item {{
      padding: 0 0 16px;
      border-bottom: 1px solid var(--rule-soft);
    }}
    .note-item:last-child {{ padding-bottom: 0; border-bottom: none; }}
    .note-label {{ margin-bottom: 7px; }}
    .note-body {{ color: var(--ink-soft); font-size: 0.92rem; line-height: 1.88; letter-spacing: 0.01em; }}
    .note-body p {{ margin: 0 0 0.9em; }}
    .note-body p:last-child {{ margin-bottom: 0; }}

    .summary-cards {{
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 12px;
      max-width: 900px;
    }}
    .summary-card {{
      display: grid;
      grid-template-columns: 28px minmax(0, 1fr);
      gap: 14px;
      padding: 18px 20px 18px 0;
      border-top: 1px solid var(--rule-soft);
    }}
    .summary-card:last-child {{ border-bottom: 1px solid var(--rule-soft); }}
    .summary-copy {{ padding-top: 0; }}
    .summary-card-title {{
      margin: 0 0 7px;
      font-size: 1rem;
      font-family: var(--font-sans);
      font-weight: 700;
      letter-spacing: 0.01em;
    }}
    .summary-card-text {{ margin: 0; font-size: 1rem; line-height: 1.86; color: var(--ink); letter-spacing: 0.01em; }}

    .module-quote {{
      display: grid;
      gap: 18px;
      justify-items: start;
      text-align: left;
      max-width: 860px;
      padding: 12px 0 64px;
    }}
    .quote-rule {{ width: min(760px, 100%); border-top: 1px solid var(--rule-soft); }}
    .quote-main {{ margin: 0; max-width: 820px; }}
    .quote-mark {{
      margin: 0 0 -6px;
      color: var(--accent-text);
      font-size: clamp(2rem, 4vw, 3.1rem);
      line-height: 0.85;
      opacity: 0.68;
    }}
    .quote-text {{
      margin: 0;
      font-family: var(--font-serif);
      font-size: clamp(1.52rem, 2.8vw, 2.42rem);
      line-height: 1.38;
      letter-spacing: -0.035em;
      text-wrap: balance;
    }}
    .quote-note, .quote-attribution {{
      margin: 0;
      max-width: 680px;
      color: var(--ink-soft);
      line-height: 1.86;
      letter-spacing: 0.01em;
    }}
    .quote-attribution {{
      font-family: var(--font-sans);
      font-size: 0.74rem;
      letter-spacing: 0.06em;
    }}

    .compare-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
      gap: 22px;
      align-items: stretch;
      max-width: 980px;
    }}
    .compare-card {{
      padding: 24px 26px;
      background: color-mix(in srgb, var(--surface) 80%, var(--bg));
      border: 1px solid var(--rule-soft);
      border-top: 2px solid var(--rule-strong);
      box-shadow: none;
    }}
    .compare-card-title {{ margin-bottom: 18px; }}
    .compare-divider {{
      align-self: center;
      display: flex;
      align-items: center;
      color: var(--accent-text);
      font-family: var(--font-sans);
      font-size: 0.72rem;
      letter-spacing: 0.08em;
      writing-mode: vertical-rl;
    }}
    .compare-list {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 14px; }}
    .compare-item {{ display: grid; gap: 5px; padding-bottom: 14px; border-bottom: 1px solid var(--rule-soft); }}
    .compare-item:last-child {{ padding-bottom: 0; border-bottom: none; }}
    .compare-label {{
      font-family: var(--font-sans);
      font-size: 0.72rem;
      color: var(--accent-text);
      letter-spacing: 0.06em;
    }}
    .compare-text {{ line-height: 1.82; letter-spacing: 0.01em; }}
    .compare-takeaway {{
      max-width: 900px;
      margin: 20px 0 0;
      padding: 15px 18px;
      border-left: 2px solid var(--accent);
      background: color-mix(in srgb, var(--accent-soft) 48%, transparent);
      color: var(--ink-soft);
      line-height: 1.82;
      letter-spacing: 0.01em;
    }}

    @media (prefers-reduced-motion: reduce) {{
      *,
      *::before,
      *::after {{
        transition-duration: 0.01ms !important;
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        scroll-behavior: auto !important;
      }}
      #reading-progress {{ transition: none; }}
    }}

    @media (max-width: 980px) {{
      body {{ padding: 30px 16px 86px; }}
      .masthead {{ padding-bottom: 34px; margin-bottom: 30px; }}
      .lead-section {{ margin-bottom: 46px; }}
      .articles-container {{ gap: 58px; }}
      .module {{ padding-bottom: 58px; }}
      .body-layout-sidenotes {{ grid-template-columns: 1fr; gap: 26px; }}
      .notes-rail {{ position: static; border-top: 1px solid var(--rule-soft); padding-top: 20px; max-width: var(--reading-width); }}
      .compare-grid {{ grid-template-columns: 1fr; gap: 14px; }}
      .compare-divider {{ justify-content: flex-start; padding-left: 2px; writing-mode: horizontal-tb; }}
    }}

    @media (max-width: 680px) {{
      body {{ padding: 24px 14px 78px; }}
      .theme-toggle {{ right: 18px; bottom: 18px; }}
      .masthead h1 {{ font-size: clamp(2.05rem, 12vw, 3rem); line-height: 1.12; }}
      .module-title, .section-title {{ font-size: clamp(1.62rem, 8.6vw, 2.35rem); line-height: 1.2; }}
      .subtitle, .module-intro, .section-lead {{ line-height: 1.82; }}
      .summary-list li {{ padding-right: 12px; }}
      .article-body {{ font-size: 1rem; line-height: 1.96; letter-spacing: 0.01em; }}
      .article-body p {{ margin-bottom: 1.42em; }}
      .article-body h1, .article-body h2, .article-body h3, .article-body h4, .article-body h5, .article-body h6 {{ margin-top: 1.85em; }}
      .summary-card {{ grid-template-columns: 1fr; gap: 8px; padding: 17px 0; }}
      .summary-copy {{ padding-top: 0; }}
      .quote-text {{ font-size: clamp(1.45rem, 8vw, 2rem); line-height: 1.42; }}
      .compare-card {{ padding: 20px 16px; }}
      pre {{ margin-left: -2px; margin-right: -2px; padding: 16px; }}
    }}

    @media print {{
      body {{ background: #fff; padding: 0; }}
      .theme-toggle, #reading-progress {{ display: none; }}
      .document-shell {{ width: 100%; }}
      .module {{ break-inside: avoid; }}
      .notes-rail {{ position: static; }}
    }}
  </style>
</head>
<body>
  <div id=\"reading-progress\"></div>

  <button class=\"theme-toggle\" type=\"button\" onclick=\"toggleTheme()\" aria-label=\"切换到深色主题\" aria-pressed=\"false\" title=\"切换到深色主题\">
    <svg class=\"icon-sun\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><circle cx=\"12\" cy=\"12\" r=\"5\"></circle><line x1=\"12\" y1=\"1\" x2=\"12\" y2=\"3\"></line><line x1=\"12\" y1=\"21\" x2=\"12\" y2=\"23\"></line><line x1=\"4.22\" y1=\"4.22\" x2=\"5.64\" y2=\"5.64\"></line><line x1=\"18.36\" y1=\"18.36\" x2=\"19.78\" y2=\"19.78\"></line><line x1=\"1\" y1=\"12\" x2=\"3\" y2=\"12\"></line><line x1=\"21\" y1=\"12\" x2=\"23\" y2=\"12\"></line><line x1=\"4.22\" y1=\"19.78\" x2=\"5.64\" y2=\"18.36\"></line><line x1=\"18.36\" y1=\"5.64\" x2=\"19.78\" y2=\"4.22\"></line></svg>
    <svg class=\"icon-moon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z\"></path></svg>
  </button>

  <main class=\"document-shell\">
    <header class=\"masthead\">
      <div class=\"masthead-meta\">生成时间：{display_date}</div>
      <h1>{esc(title)}</h1>
      {subtitle_html}
      {tag_html(tags)}
    </header>

    {summary_html}

    <div class=\"articles-container\">
      {''.join(render_module(section, i + 1, body_variant) for i, section in enumerate(sections))}
    </div>
  </main>

  <script>
    const themeToggle = document.querySelector('.theme-toggle');
    const progressBar = document.getElementById('reading-progress');

    function applyTheme(theme) {{
      const next = theme === 'dark' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', next);
      if (themeToggle) {{
        const isDark = next === 'dark';
        const label = isDark ? '切换到浅色主题' : '切换到深色主题';
        themeToggle.setAttribute('aria-label', label);
        themeToggle.setAttribute('aria-pressed', String(isDark));
        themeToggle.setAttribute('title', label);
      }}
    }}

    function updateReadingProgress() {{
      if (!progressBar) {{ return; }}
      const winScroll = document.body.scrollTop || document.documentElement.scrollTop;
      const height = document.documentElement.scrollHeight - document.documentElement.clientHeight;
      const progress = height > 0 ? winScroll / height : 0;
      progressBar.style.transform = 'scaleX(' + Math.min(1, Math.max(0, progress)) + ')';
    }}

    function toggleTheme() {{
      const current = document.documentElement.getAttribute('data-theme');
      const next = current === 'light' ? 'dark' : 'light';
      applyTheme(next);
      localStorage.setItem('claude_html_theme', next);
    }}

    window.addEventListener('DOMContentLoaded', () => {{
      const savedTheme = localStorage.getItem('claude_html_theme') || 'light';
      applyTheme(savedTheme);
      updateReadingProgress();
    }});

    window.addEventListener('scroll', updateReadingProgress, {{ passive: true }});
  </script>
  {mathjax_html}
</body>
</html>
"""

    out = Path(output).expanduser().resolve()
    out.write_text(html_doc, encoding="utf-8")
    Path(stamp).expanduser().write_text(generated_at, encoding="utf-8")
    Path(sidecar).expanduser().write_text(str(out), encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()
