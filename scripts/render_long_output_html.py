#!/usr/bin/env python3
"""Render structured JSON longform output as a self-contained editorial HTML page.

Design system: "green print" — deep green-ink paper (#33452f) with cream type
(#ece2cb), Songti Black display, seal/woodcut/plate vocabulary, torn-paper
transitions, and a scroll-driven print-shop motion layer (CSS scroll timelines,
gated behind prefers-reduced-motion and @supports).

Input: JSON on stdin (schema in skills/long-output-html/SKILL.md).
Output: writes the HTML file, updates the stamp and sidecar, prints the path.
"""
import html
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

import mistune

try:
    from pygments.formatters.html import HtmlFormatter
    from pygments.lexers import get_lexer_by_name
    from pygments.util import ClassNotFound
    from pygments.styles import get_style_by_name

    _PYGMENTS_AVAILABLE = True
except Exception:
    _PYGMENTS_AVAILABLE = False

DEFAULT_OUTPUT_DIR = "/tmp"
DEFAULT_OUTPUT_PREFIX = "claude-long-output"
DEFAULT_STAMP = "/tmp/claude-long-output.stamp"
DEFAULT_SIDECAR = "/tmp/claude-last-html-path.txt"
SUPPORTED_SECTION_TYPES = {"body", "summary", "quote", "compare", "figure"}
SUPPORTED_BODY_VARIANTS = {"narrative", "sidenotes"}
SUPPORTED_THEMES = {"green", "paper"}
CN_NUM = ["壹", "贰", "叁", "肆", "伍", "陆", "柒", "捌", "玖", "拾"]

PRE_CODE_RE = re.compile(
    r'<pre><code(?: class="language-([\w#+.\-]+)")?>(.*?)</code></pre>', re.DOTALL
)
TABLE_WRAP_RE = re.compile(r"<table>.*?</table>", re.DOTALL)
DROP_CAP_RE = re.compile(r"^(<p[^>]*>)(?!<)([^<\s])([\s\S]*?</p>)")


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def cn_num(n: int) -> str:
    return CN_NUM[n - 1] if 1 <= n <= len(CN_NUM) else f"{n:02d}"


def _highlight_one(code_html: str, lang: str):
    if not _PYGMENTS_AVAILABLE or not lang:
        return None
    code = html.unescape(code_html)
    try:
        lexer = get_lexer_by_name(lang, stripnl=False)
    except ClassNotFound:
        return None
    formatter = HtmlFormatter(nowrap=True)
    return pygments_highlight(code, lexer, formatter)


def pygments_highlight(code, lexer, formatter):
    from pygments import highlight as _highlight

    return _highlight(code, lexer, formatter)


PLAIN_PRE_RE = re.compile(r"<pre><code>(.*?)</code></pre>", re.DOTALL)


def highlight_code_blocks(html_str: str) -> str:
    if "language-" not in html_str:
        return PLAIN_PRE_RE.sub(
            r'<div class="code-plate"><pre><code>\1</code></pre></div>', html_str
        )

    def repl(match):
        lang = match.group(1) or ""
        highlighted = _highlight_one(match.group(2), lang)
        if highlighted is None:
            return match.group(0)
        return f'<div class="code-plate"><div class="highlight"><pre><code>{highlighted}</code></pre></div></div>'

    return PRE_CODE_RE.sub(repl, html_str)


def markdown_to_html(text: str) -> str:
    if not text:
        return ""
    renderer = mistune.create_markdown(
        escape=False,
        plugins=["strikethrough", "table", "task_lists", "footnotes"],
    )
    out = highlight_code_blocks(renderer(str(text).strip()))
    return TABLE_WRAP_RE.sub(r'<div class="table-wrap">\g<0></div>', out)


def _pygments_css_for_style(style_name, scope: str) -> str:
    if not _PYGMENTS_AVAILABLE or not style_name:
        return ""
    try:
        css = HtmlFormatter(style=style_name).get_style_defs(".highlight")
    except Exception:
        return ""
    scoped_lines = []
    for line in css.splitlines():
        stripped = line.strip()
        if stripped.startswith("."):
            scoped_lines.append(f"{scope} {line}")
        else:
            scoped_lines.append(line)
    return "\n".join(scoped_lines)


def _pick_pygments_style(candidates):
    if not _PYGMENTS_AVAILABLE:
        return None
    for name in candidates:
        try:
            get_style_by_name(name)
            return name
        except Exception:
            continue
    return None


def build_pygments_css() -> str:
    if not _PYGMENTS_AVAILABLE:
        return ""
    style = _pick_pygments_style(["gruvbox-dark", "monokai", "native"])
    css = _pygments_css_for_style(style, ".code-plate .highlight")
    overrides = """
    .code-plate .highlight, .code-plate .highlight pre {
      background: transparent !important;
    }"""
    return f"\n    /* syntax highlighting (pygments, scoped to the code plate) */\n    {css}\n    {overrides}"


def list_items(items, class_name="deck-list"):
    if not items:
        return ""
    lis = []
    for i, item in enumerate(items, start=1):
        text = str(item).strip()
        if text:
            lis.append(
                f'<li><span class="deck-idx">{i:02d}</span>'
                f'<span class="deck-text">{esc(text)}</span></li>'
            )
    return f'<ol class="{class_name}">{"".join(lis)}</ol>' if lis else ""


def tag_html(tags):
    if not tags:
        return ""
    chips = " · ".join(esc(tag) for tag in tags if str(tag).strip())
    return f'<div class="vtags">{chips}</div>' if chips else ""


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


def normalize_figure(section):
    """figure module: tick-rows plate (skeleton from lieflat-charts C1)."""
    unit_step = section.get("unit_step", 0.1)
    try:
        unit_step = abs(float(unit_step)) or 0.1
    except (TypeError, ValueError):
        unit_step = 0.1
    rows = []
    for i, row in enumerate(section.get("rows") or []):
        if isinstance(row, dict):
            label = str(row.get("label") or "").strip()
            value = row.get("value")
            display = str(row.get("display") or "").strip()
            hero = bool(row.get("hero"))
        else:
            label, value, display, hero = str(row).strip(), None, "", False
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "label": label or f"{i:02d}",
                "value": value,
                "display": display or f"{value:g}",
                "hero": hero,
            }
        )
    if not rows:
        return None
    if not any(row["hero"] for row in rows):
        rows[-1]["hero"] = True
    return {
        "title": str(section.get("title") or "").strip(),
        "sub": str(section.get("sub") or section.get("lead") or "").strip(),
        "source": str(section.get("source") or "").strip(),
        "unit_step": unit_step,
        "rows": rows,
    }


def render_tickrows(fig):
    """Chart skeleton from lieflat-charts basics-gallery C1 · tick rows:
    1 tick = 1 unit, row-end big number, dot marks every fifth, seeded jitter."""
    import random as _r

    rnd = _r.Random(42)
    unit_step = fig["unit_step"]
    rows = fig["rows"]
    X0, PX = 150, 8.4
    out = []
    for i, row in enumerate(rows):
        y = 44 + i * 62
        ticks = max(1, min(70, round(abs(row["value"]) / unit_step)))
        opacity = "1" if row["hero"] else ".55"
        label_op = "1" if row["hero"] else ".75"
        out.append('<g class="figrow">')
        out.append('<g class="tickband" aria-hidden="true">')
        out.append(
            f'<text x="128" y="{y + 4}" text-anchor="end" font-size="12.5" '
            f'font-weight="600" letter-spacing=".08em" fill="currentColor" '
            f'opacity="{label_op}">{esc(row["label"])}</text>'
        )
        out.append(
            f'<line x1="{X0}" y1="{y + 9}" x2="{X0 + ticks * PX:.1f}" y2="{y + 9}" '
            f'stroke="currentColor" stroke-width=".7" opacity=".28"/>'
        )
        for k in range(ticks):
            x = X0 + k * PX + PX / 2
            h = 9 + rnd.random() * 6
            o = (0.9 + rnd.random() * 0.1) if row["hero"] else (0.55 + rnd.random() * 0.45)
            out.append(
                f'<line x1="{x:.1f}" y1="{y + 9}" x2="{x:.1f}" y2="{y + 9 - h:.1f}" '
                f'stroke="currentColor" stroke-width="1.1" opacity="{o:.2f}"/>'
            )
            if k % 5 == 4:
                out.append(
                    f'<circle cx="{x:.1f}" cy="{y + 13.5}" r="1" '
                    f'fill="currentColor" opacity=".55"/>'
                )
        out.append("</g>")
        out.append(
            f'<text x="{X0 + ticks * PX + 12:.1f}" y="{y + 5}" font-size="15" '
            f'font-weight="800" fill="currentColor">{esc(row["display"])}</text>'
        )
        out.append("</g>")
    out.append(
        f'<text x="320" y="232" text-anchor="middle" font-size="9.5" '
        f'font-weight="600" letter-spacing=".14em" fill="currentColor" opacity=".55">'
        f'ONE TICK = {unit_step:g} · DOT MARKS EVERY FIFTH</text>'
    )
    aria = (
        "Tick-row chart. "
        + "; ".join(f'{r["label"]} {r["display"]}' for r in rows)
        + f". One tick equals {unit_step:g}."
    )
    return (
        '<svg class="fig-svg" viewBox="0 0 640 240" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="{esc(aria)}">' + "".join(out) + "</svg>"
    )


def add_drop_cap(content_html: str):
    """Wrap the first glyph of the first paragraph as a display drop cap.

    A visually-hidden copy of the glyph keeps the text stream intact for
    screen readers (the visible cap is aria-hidden)."""
    match = DROP_CAP_RE.search(content_html)
    if not match:
        return content_html
    open_tag, first_char, rest = match.group(1), match.group(2), match.group(3)
    if not re.match(r"[\u4e00-\u9fffA-Za-z0-9]", first_char):
        return content_html
    replacement = (
        f'{open_tag}<span class="dropcap" aria-hidden="true">{first_char}</span>'
        f'<span class="sr-first-char">{first_char}</span>{rest}'
    )
    return content_html[: match.start()] + replacement + content_html[match.end():]


def table_label(count: int) -> str:
    return (
        f'<div class="fig-kicker" aria-hidden="true">表版 · {cn_num(count)}'
        f" &nbsp;&nbsp; SPECIMEN TABLE</div>"
    )


def sunburst(color="currentColor", rays=16, r_out=20, r_in=8.5, size=40):
    import math

    cx = cy = size / 2
    pts = []
    for i in range(2 * rays):
        a = math.pi * i / rays - math.pi / 2
        r = r_out if i % 2 == 0 else r_in
        pts.append(f"{cx + r*math.cos(a):.2f},{cy + r*math.sin(a):.2f}")
    return (
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" aria-hidden="true">'
        f'<polygon points="{" ".join(pts)}" fill="{color}"/></svg>'
    )


def torn_edge(paper_above: bool, seed: int, paper="#e8dfcd", ink="#3c523b", h=64):
    """Torn-paper boundary. `paper` is the sheet colour drawn over `ink`."""
    import random as _r

    rnd = _r.Random(seed)
    pts = [(0.0, 28.0)]
    x = 0.0
    while x < 1440:
        x += rnd.randint(10, 24)
        if x > 1440:
            x = 1440
        y = 28 + rnd.randint(-13, 13)
        pts.append((float(x), float(y)))
        if rnd.random() < 0.4:
            pts.append((min(x + rnd.randint(2, 5), 1440), float(y + rnd.randint(-6, 6))))
    pts.append((1440.0, 28.0))
    if paper_above:
        d = "M0,0 L1440,0 " + " ".join(f"L{x},{y}" for x, y in reversed(pts)) + " Z"
    else:
        d = f"M0,{h} L1440,{h} " + " ".join(f"L{x},{y}" for x, y in reversed(pts)) + " Z"
    return (
        f'<div class="tear" style="background:{ink}" aria-hidden="true">'
        f'<svg viewBox="0 0 1440 {h}" preserveAspectRatio="none">'
        f'<path fill="{paper}" d="{d}"/></svg></div>'
    )


def branch_path(color="currentColor"):
    import math as _m

    p0, p1, p2 = (24, 192), (86, 118), (182, 22)

    def bez(t):
        return ((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])

    def tangent(t):
        dx = 2 * (1 - t) * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0])
        dy = 2 * (1 - t) * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1])
        return _m.atan2(dy, dx)

    parts = [
        f'<path d="M{p0[0]},{p0[1]} Q{p1[0]},{p1[1]} {p2[0]},{p2[1]}" fill="none" '
        f'stroke="{color}" stroke-width="3.6" stroke-linecap="round"/>'
    ]
    leaves = 7
    for i in range(leaves):
        t = 0.14 + i * (0.72 / (leaves - 1))
        x, y = bez(t)
        ang = tangent(t)
        fade = 1 - 0.45 * i / leaves
        rx, ry = 21 * fade + 6, 7 * fade + 2.5
        for side in (1, -1):
            if i == leaves - 1 and side == -1:
                continue
            off = 15 - 3 * i / leaves
            nx, ny = _m.cos(ang + _m.pi / 2), _m.sin(ang + _m.pi / 2)
            lx, ly = x + nx * off * side, y + ny * off * side
            la = _m.degrees(ang) + 42 * side
            parts.append(
                f'<ellipse cx="{lx:.1f}" cy="{ly:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" '
                f'fill="{color}" transform="rotate({la:.1f} {lx:.1f} {ly:.1f})"/>'
            )
    tx, ty = bez(1.0)
    ta = _m.degrees(tangent(1.0))
    parts.append(
        f'<ellipse cx="{tx + 8:.1f}" cy="{ty - 6:.1f}" rx="16" ry="5.5" fill="{color}" '
        f'transform="rotate({ta:.1f} {tx + 8:.1f} {ty - 6:.1f})"/>'
    )
    return (
        '<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        + "".join(parts)
        + "</svg>"
    )


def fan(color="currentColor", rays=30, r_in=150, r_out=360):
    import math as _m

    parts = []
    for i in range(rays):
        a = -160 + i * (320 / (rays - 1))
        parts.append(f'<line x1="0" y1="{-r_in}" x2="0" y2="{-r_out}" transform="rotate({a:.1f})"/>')
    arc = (
        f"M {r_in * _m.cos(_m.radians(-160)):.1f} {r_in * _m.sin(_m.radians(-160)):.1f} "
        f"A {r_in} {r_in} 0 1 1 {r_in * _m.cos(_m.radians(-20)):.1f} "
        f"{r_in * _m.sin(_m.radians(-20)):.1f}"
    )
    parts.append(f'<path d="{arc}" fill="none"/>')
    return (
        '<svg viewBox="-400 -400 800 420" xmlns="http://www.w3.org/2000/svg" '
        f'stroke="{color}" stroke-width="2.4" fill="none" aria-hidden="true">'
        + "".join(parts)
        + "</svg>"
    )


CSS_BASE = r"""
    :root{
      --paper:#e8dfcd; --bg:#33452f; --ink:#ece2cb; --ink-soft:rgba(236,226,203,.70);
      --hairline:rgba(236,226,203,.22); --rule-ink:#d5caa9;
      --accent:#ece2cb; --accent-deep:#3c523b; --on-accent:#33452f;
      --sheet-bg:#e8dfcd; --sheet-ink:#3c523b;
      --sheet-line:rgba(60,82,59,.35); --sheet-line-soft:rgba(60,82,59,.15);
      --sheet-seal-bg:#ece2cb; --sheet-seal-fg:#3c523b;
      --panel:rgba(236,226,203,.07); --ghost-page:rgba(236,226,203,.08);
      --fig-bg:#e8dfcd; --fig-ink:#3c523b;
      --font-display:"Songti SC","STSong",serif;
      --font-body:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
      --font-serif:"Songti SC","STSong",Georgia,serif;
      --font-label:"PingFang SC",sans-serif;
      --font-mono:"JetBrainsMono Nerd Font","JetBrains Mono",ui-monospace,Menlo,monospace;
    }
    [data-theme="paper"]{
      --bg:#e8dfcd; --ink:#3c523b; --ink-soft:rgba(60,82,59,.72);
      --hairline:rgba(60,82,59,.24); --rule-ink:#3c4a38;
      --accent:#3c523b; --accent-deep:#3c523b; --on-accent:#ece2cb;
      --sheet-bg:#3c523b; --sheet-ink:#ece2cb;
      --sheet-line:rgba(236,226,203,.32); --sheet-line-soft:rgba(236,226,203,.15);
      --sheet-seal-bg:#ece2cb; --sheet-seal-fg:#3c523b;
      --panel:rgba(60,82,59,.06); --ghost-page:rgba(60,82,59,.10);
      --fig-bg:#3c523b; --fig-ink:#ece2cb;
    }
    [data-theme="paper"] .tear{display:none}
    *{box-sizing:border-box} html,body{margin:0;padding:0}
    ::selection{background:rgba(236,226,203,.28);color:#f5efdd}
    .spread ::selection{background:rgba(60,82,59,.22)}
    body{background:var(--bg);color:var(--ink);font-family:var(--font-body);
      font-size:17px;line-height:1.85;-webkit-font-smoothing:antialiased;font-kerning:normal}
    body::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:999;opacity:.10;mix-blend-mode:soft-light;
      background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='260' height='260'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='260' height='260' filter='url(%23n)'/%3E%3C/svg%3E");
      background-size:260px 260px}
    .top-rule{height:4px;background:#ece2cb}
    .shell{max-width:1160px;margin:0 auto;padding:0 44px}

    /* ---- cover ---- */
    .cover{position:relative;padding:30px 0 0;text-align:center}
    .cover-meta{display:flex;justify-content:space-between;align-items:flex-start;text-align:left;
      font-family:var(--font-label);font-size:12.5px;font-weight:600;letter-spacing:.2em;color:var(--ink-soft)}
    .seal{width:48px;height:48px;background:var(--accent);color:var(--on-accent);
      font-family:"Kaiti SC","Kaiti TC",serif;font-weight:700;font-size:26px;line-height:1;
      display:grid;place-items:center;transform:rotate(-4deg);position:relative}
    .seal::after{content:"";position:absolute;inset:3px;border:1px solid currentColor;opacity:.5}
    .cover .seal{margin-top:-10px}
    .ghost{position:absolute;top:-50px;right:0;font-family:var(--font-display);font-weight:900;
      font-size:370px;line-height:1;color:rgba(236,226,203,.04);pointer-events:none;user-select:none;z-index:0;
      -webkit-text-stroke:2px rgba(236,226,203,.34)}
    .cover-fan{position:absolute;left:50%;top:118px;transform:translateX(-50%);width:780px;
      pointer-events:none;user-select:none;z-index:0}
    .cover-fan svg{display:block;width:100%;height:auto}
    .cover-meta{position:relative;z-index:2;align-items:center}
    .cover-meta::before{content:"";flex:1;height:1px;background:var(--hairline);margin-right:22px}
    .cover-meta::after{content:"";flex:1;height:1px;background:var(--hairline);margin-left:22px}
    .orn-row{margin-top:38px;display:flex;align-items:center;justify-content:center;gap:14px;position:relative;z-index:1}
    .orn-row .ol,.orn-row .or{width:110px;height:1px;background:rgba(236,226,203,.35)}
    .orn-row .od{width:7px;height:7px;background:#ece2cb;transform:rotate(45deg)}
    .orn-row .seal-mini{margin-left:4px}
    .sunmark{display:block;margin:0 auto}
    h1.title{position:relative;z-index:1;margin:30px auto 0;font-family:var(--font-display);font-weight:900;
      font-size:84px;line-height:1.14;max-width:16em}
      text-wrap:balance
    .standfirst{position:relative;z-index:1;margin:26px auto 0;max-width:28em;font-family:var(--font-serif);
      font-size:20px;line-height:1.8;color:var(--ink-soft)}
    .branch.c1b{bottom:-40px;right:140px;width:195px;opacity:.5;transform:rotate(-158deg)}
    .branch.c4{right:-16px;bottom:120px;width:210px;opacity:.13;transform:rotate(-118deg);color:var(--ink)}
    .vtags{position:absolute;right:0;top:250px;writing-mode:vertical-rl;
      font-family:var(--font-label);font-size:11px;font-weight:700;letter-spacing:.42em;
      color:var(--accent);border-left:1px solid var(--hairline);padding-left:12px;height:230px;z-index:1}
    .rule-double{height:7px;border-top:3px solid var(--rule-ink);border-bottom:1px solid var(--rule-ink);position:relative}
    .rule-double::after{content:"";position:absolute;left:50%;top:50%;transform:translate(-50%,-50%) rotate(45deg);
      width:9px;height:9px;background:var(--paper);border:1.5px solid var(--rule-ink)}

    /* ---- tears ---- */
    .tear svg{display:block;width:100%;height:54px}

    /* ---- module grid: number BELOW the rule, no overlap ---- */
    .module{padding:56px 0 8px}
    .module .rule-double{margin-bottom:30px}
    .mgrid{display:grid;grid-template-columns:118px minmax(0,42em);column-gap:38px;justify-content:center}
    .sec-num{font-family:var(--font-display);font-weight:900;font-size:104px;line-height:.85;color:var(--accent)}
    .kicker{display:flex;align-items:center;gap:12px;font-family:var(--font-label);
      font-size:13px;font-weight:700;letter-spacing:.26em;color:var(--accent)}
    .kicker::before{content:"";width:7px;height:7px;background:var(--accent);transform:rotate(45deg);flex:none}
    .kicker::after{content:"";flex:1;height:1px;background:var(--hairline)}
    .kicker.k-seal::before{display:none}
    .numseal{flex:none;width:21px;height:21px;background:var(--accent);color:var(--on-accent);
      font-family:"Kaiti SC","Kaiti TC",serif;font-weight:700;font-size:13px;line-height:1;
      display:grid;place-items:center;transform:rotate(-4deg)}
    .body-inner{hanging-punctuation:allow-end first}
    h2.sec-title{margin:18px 0 0;font-family:var(--font-display);font-weight:900;
      font-size:42px;line-height:1.24;max-width:20em}
    .sec-lead{margin:16px 0 0;max-width:40em;font-family:var(--font-serif);
      font-size:18.5px;line-height:1.85;color:var(--ink-soft)}
    .body-inner{max-width:42em;margin-top:30px}
    .body-inner p{margin:0 0 1.35em;text-align:justify;text-indent:2em}
    .body-inner p.noindent{text-indent:0}
    .body-inner blockquote p{text-indent:0}
    .body-inner strong{font-weight:600;text-emphasis:filled circle rgba(236,226,203,.85);
      -webkit-text-emphasis:filled circle rgba(236,226,203,.85);
      text-emphasis-position:under right;-webkit-text-emphasis-position:under right}
    .dropcap{float:left;font-family:var(--font-display);font-weight:900;font-size:58px;line-height:.9;
      color:var(--accent);margin:8px 14px 0 0}

    /* ---- table: same column width, centered, column rules ---- */
    .breakout{margin:34px 0 10px;width:42em;max-width:100%}
    table{width:100%;border-collapse:collapse;font-size:15.5px;line-height:1.75;
      border-top:2px solid var(--rule-ink);border-bottom:2px solid var(--rule-ink)}
    th{font-family:var(--font-label);font-size:12.5px;font-weight:700;letter-spacing:.18em;
      color:var(--accent);text-align:center;padding:12px 14px;border-bottom:2px solid var(--rule-ink)}
    td{padding:13px 14px;border-bottom:1px solid var(--hairline);vertical-align:top;text-align:center}
    tr:last-child td{border-bottom:none}
    th+th,td+td{border-left:1px solid var(--hairline)}
    td:first-child{font-family:var(--font-serif);font-weight:600}

    /* ---- code plate ---- */
    .code-plate{margin:34px 0 10px;width:42em;max-width:100%;background:#243020;color:#e3ddc4;
      padding:22px 26px;position:relative;border-left:3px solid var(--accent)}
    .code-plate::before{content:"CODE";position:absolute;top:10px;right:14px;
      font-family:var(--font-label);font-size:10px;font-weight:700;letter-spacing:.34em;opacity:.4}
    .code-plate pre{margin:0;font-family:var(--font-mono);font-size:14px;line-height:1.8;overflow-x:auto}
    .code-plate .cm{opacity:.55}

    /* ---- note cards at section bottom ---- */
    .notecards{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-top:36px;width:42em;max-width:100%}
    .notecard{border:1px solid var(--hairline);border-top:2px solid var(--accent);padding:16px 18px;background:var(--panel)}
    .notecard-head{display:flex;align-items:center;gap:8px;margin-bottom:8px}
    .tag-seal{display:inline-grid;place-items:center;min-width:20px;height:20px;padding:0 5px;
      background:var(--accent);color:var(--on-accent);font-family:"Kaiti SC",serif;font-weight:700;font-size:12px}
    .notecard-label{font-family:var(--font-label);font-size:11.5px;font-weight:700;letter-spacing:.2em;color:var(--accent)}
    .notecard-body{font-size:13.5px;line-height:1.8;color:var(--ink-soft)}

    /* ---- framed pull-quote ---- */
    .pullframe{margin:34px 0 0;width:42em;max-width:100%;border:1px solid var(--hairline);border-left:3px solid var(--accent);
      padding:20px 26px;font-family:var(--font-serif);font-size:19px;line-height:1.8;color:var(--accent);font-weight:600;background:var(--panel)}

    /* ---- full-bleed spread ---- */
    .spread{background:var(--sheet-bg);color:var(--sheet-ink);overflow:hidden}
    .spread-inner{max-width:900px;margin:0 auto;padding:92px 44px 100px;position:relative}
    .spread-inner::before{content:"";position:absolute;inset:20px 26px;border:1px solid var(--sheet-line);pointer-events:none}
    .spread-inner::after{content:"";position:absolute;inset:27px 33px;border:1px solid var(--sheet-line-soft);pointer-events:none}
    .ghost-q{position:absolute;left:34px;top:6px;font-family:var(--font-serif);font-weight:900;
      font-size:190px;line-height:1;color:var(--sheet-ink);opacity:.1;pointer-events:none;user-select:none}
    .ghost-sun{position:absolute;right:48px;bottom:36px;opacity:.28;pointer-events:none;color:var(--sheet-ink)}
    .spread .kicker{color:var(--accent-deep);position:relative}
    .spread .kicker::before{background:var(--accent-deep)}
    .spread .kicker::after{background:var(--sheet-line)}
    .q-text .ql{display:block}
    .q-text{margin:26px 0 0;font-family:var(--font-display);font-weight:900;
      font-size:42px;line-height:1.5;max-width:23em;position:relative}
    .q-note{margin:22px 0 0;max-width:36em;font-size:15.5px;line-height:1.8;opacity:.92;position:relative}
    .q-attr{margin:28px 0 0;font-family:var(--font-label);font-size:12px;font-weight:600;letter-spacing:.24em;opacity:.92;position:relative}
    .seal-mini{display:inline-grid;place-items:center;width:22px;height:22px;background:var(--on-accent);
      color:var(--accent-deep);font-family:"Kaiti SC",serif;font-weight:700;font-size:13px;margin-left:12px;vertical-align:-4px}

    /* ---- triple ---- */
    .triple{display:grid;grid-template-columns:repeat(3,1fr);gap:32px;margin-top:34px;width:42em;max-width:100%}
    .triple .cell{border-top:2px solid var(--rule-ink);padding-top:14px}
    .cell .idx{font-family:var(--font-label);font-size:13px;font-weight:700;letter-spacing:.14em;color:var(--accent);font-variant-numeric:tabular-nums}
    .cell h3{margin:8px 0 0;font-family:var(--font-display);font-weight:900;font-size:20px;line-height:1.4}
    .cell p{margin:8px 0 0;font-size:14px;line-height:1.8;color:var(--ink-soft)}

    /* ---- compare ---- */
    .compare{display:grid;grid-template-columns:1fr auto 1fr;gap:26px;margin-top:34px;width:42em;max-width:100%}
    .cmp-card{border-top:2px solid var(--rule-ink);padding-top:16px}
    .cmp-title{font-family:var(--font-display);font-weight:900;font-size:21px}
    .cmp-item{padding:12px 0;border-bottom:1px solid var(--hairline)}
    .cmp-item:last-child{border-bottom:none}
    .cmp-label{font-family:var(--font-label);font-size:11.5px;font-weight:700;letter-spacing:.22em;color:var(--accent)}
    .cmp-text{margin-top:4px;font-size:14.5px;line-height:1.75}
    .cmp-divider{align-self:start;padding-top:18px;writing-mode:vertical-rl;
      font-family:var(--font-label);font-size:12px;font-weight:700;letter-spacing:.3em;color:var(--accent)}
    .takeaway{margin:30px 0 0;max-width:42em;font-family:var(--font-serif);font-size:18px;line-height:1.85}
    .takeaway::before{content:"";display:inline-block;width:10px;height:10px;background:var(--accent);margin-right:12px}

    /* ---- deck ---- */
    .deck-list{list-style:none;margin:26px 0 0;padding:0;max-width:42em}
    .deck-list li{display:grid;grid-template-columns:2.4em 1fr;gap:14px;padding:11px 0;border-bottom:1px solid var(--hairline)}
    .deck-list li:last-child{border-bottom:none}
    .deck-idx{font-family:var(--font-label);font-size:13px;font-weight:700;color:var(--accent);padding-top:.28em;font-variant-numeric:tabular-nums}
    .deck-text{font-size:17px;line-height:1.8}

    /* ---- ghost numeral (on paper) ---- */
    .module{position:relative}
    .ghost-num{position:absolute;left:calc(50% + 292px);bottom:2px;font-family:var(--font-display);font-weight:900;
      font-size:200px;line-height:1;color:var(--ghost-page);pointer-events:none;user-select:none;z-index:0}
    .mgrid{position:relative;z-index:1}

    /* ---- end ---- */
    .end-band{background:var(--sheet-bg);color:var(--sheet-ink);overflow:hidden}
    .end-band .band-inner{max-width:860px;margin:0 auto;padding:56px 44px 72px;text-align:center;position:relative}
    .end-band .sunmark{margin:0 auto 18px}
    .end-band .seal{background:var(--accent-deep);color:var(--paper);margin:0 auto}
    .end-band .end-meta{margin-top:22px;font-family:var(--font-label);font-size:11.5px;font-weight:600;letter-spacing:.3em;color:var(--on-accent);opacity:.92}

    /* ---- mobile degradation: single column, scrollable tables ---- */
    @media (max-width: 860px){
      body{font-size:16px}
      .shell{padding:0 22px}
      .breakout{overflow-x:auto}
      .mgrid{grid-template-columns:minmax(0,1fr);column-gap:0}
      .mgrid > div{min-width:0}
      .sec-num{font-size:60px;margin-bottom:10px}
      .notecards,.triple,.compare{grid-template-columns:1fr;width:auto}
      .cmp-divider{writing-mode:horizontal-tb;padding:4px 0}
      .ghost{font-size:190px;top:-24px;right:0;-webkit-text-stroke-width:1.2px}
      .ghost-num{display:none}
      h1.title{font-size:clamp(38px,10.5vw,54px)}
      .standfirst{font-size:17px}
      .vtags{display:none}
      .deck-list li{grid-template-columns:2em 1fr;gap:10px}
      .code-plate{width:auto}
      .rule-double::after{width:7px;height:7px}
    }

    /* ---- v9: green cover + green middle sheet ---- */
    .cover-wrap{color:var(--ink)}
    .top-rule{background:var(--accent)}
    .cover-wrap .cover-meta{color:rgba(236,226,203,.82)}
    .cover-wrap .cover-meta::before,.cover-wrap .cover-meta::after{background:rgba(236,226,203,.35)}
    .cover-wrap .cover .seal{background:#ece2cb;color:#3c523b}
    .cover-wrap .ghost{color:rgba(236,226,203,.05);-webkit-text-stroke-color:rgba(236,226,203,.42)}
    .cover-wrap .standfirst{color:rgba(236,226,203,.8)}
    .cover-wrap .vtags{color:var(--on-accent);border-left-color:rgba(236,226,203,.35)}
    .cover-wrap .orn-row .ol,.cover-wrap .orn-row .or{background:rgba(236,226,203,.35)}
    .cover-wrap .orn-row .od{background:#ece2cb}
.cover-wrap .orn-row .seal-mini{background:#ece2cb;color:#3c523b}
    .cover-wrap .orn-row .seal-mini{background:var(--sheet-seal-bg);color:var(--sheet-seal-fg)}
    .greensheet .branch.c5{left:-26px;bottom:-30px;right:auto;width:230px;opacity:.22;transform:rotate(14deg)}

    /* ---- figure plate: 图版 (chart skeleton from lieflat-charts C1) ---- */
    .figure-plate{background:var(--fig-bg);color:var(--fig-ink);padding:24px 28px 18px;
      margin:36px 0 10px;width:42em;max-width:100%;border-top:2px solid var(--fig-ink)}
    .fig-kicker{font-family:var(--font-label);font-size:11px;font-weight:700;letter-spacing:.26em;
      color:var(--fig-ink);opacity:.85;margin-bottom:10px}
    .fig-title{font-family:var(--font-display);font-weight:900;font-size:21px;line-height:1.4;margin-bottom:4px;color:var(--fig-ink)}
    .fig-sub{font-size:12.5px;line-height:1.7;color:var(--fig-ink);opacity:.85;margin-bottom:16px}
    .fig-svg{display:block;width:100%;height:auto}
    .fig-svg .figrow,.fig-svg .tickband{opacity:1}
    .fig-src{margin-top:12px;font-family:var(--font-label);font-size:11.5px;font-weight:600;
      letter-spacing:.12em;color:var(--fig-ink);opacity:.85}
    .breakout .fig-kicker{margin:-6px 0 8px}

    /* ---- organic layer: botanical branches ---- */
    .branch{position:absolute;pointer-events:none;user-select:none;z-index:3}
    .branch svg{display:block;width:100%;height:auto}
    .branch.c1{top:-24px;left:60px;width:235px;transform:rotate(16deg);color:#ece2cb}
    .branch.c1 svg{transform-origin:12% 92%}
    .branch.c2{right:26px;bottom:-12px;width:250px;opacity:.32;transform:rotate(8deg) scaleX(-1);color:var(--sheet-ink)}
    .branch.c2 svg{transform-origin:80% 90%}
    .branch.c3{right:4px;top:-28px;width:210px;opacity:.3;transform:rotate(148deg);color:var(--sheet-ink)}

    /* ---- motion layer: 印刷车间 print-shop vocabulary ---- */
    :root{--ease-out:cubic-bezier(.22,1,.36,1);--ease-stamp:cubic-bezier(.3,1.4,.5,1)}
    #reading-progress{position:fixed;top:0;left:0;height:3px;width:100%;background:var(--accent);
      transform-origin:0 50%;transform:scaleX(0);z-index:1200;pointer-events:none}
    .notecard{transition:transform .18s var(--ease-out),border-color .18s var(--ease-out)}
    .notecard:hover{transform:translateY(-2px);border-color:var(--accent)}
    td{transition:background .15s ease}
    tr:hover td{background:rgba(236,226,203,.06)}

    @media print{
      #reading-progress{display:none}
      *,*::before,*::after{animation:none !important}
      body{background:#fff !important;color:#28211a}
      body::after,.branch,.cover-fan,.ghost,.ghost-num,.ghost-q,.ghost-sun,.tear,.top-rule,#reading-progress,.reg{display:none !important}
      .spread,.end-band{background:#fff !important}
      .spread *,.end-band *{color:#28211a !important}
      .cover .seal,.end-band .seal,.numseal,.tag-seal,.seal-mini{background:#28211a !important;color:#fff !important;transform:rotate(-4deg)}
      .code-plate{background:#f0f0f0 !important;color:#28211a !important;border:1px solid #bbb}
      a{text-decoration:none}
    }

    /* load sequence: the cover sets the stage (top-of-page = load clock, not scroll) */
    @media (prefers-reduced-motion: no-preference){
      .cover-meta{animation:rise .55s var(--ease-out) both}
      .ghost{animation:fade-in 1.4s ease .1s both}
      .cover .sunmark{animation:stamp-flat .5s var(--ease-stamp) .38s both}
      .cover .seal{animation:stamp-tilt .45s var(--ease-stamp) .62s both}
      h1.title{animation:rise .65s var(--ease-out) .2s both}
      .standfirst{animation:rise .65s var(--ease-out) .34s both}
      .vtags{animation:fade-in .9s ease .75s both}
      @keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
      @keyframes fade-in{from{opacity:0}to{opacity:1}}
      @keyframes stamp-flat{0%{opacity:0;transform:scale(1.55) rotate(-10deg)}55%{opacity:1}100%{opacity:1;transform:none}}
      @keyframes stamp-tilt{0%{opacity:0;transform:scale(1.55) rotate(-14deg)}55%{opacity:1}100%{opacity:1;transform:rotate(-4deg)}}
    }

    /* scroll-scrubbed devices: below-the-fold only, transform/opacity/clip-path only */
    @supports (animation-timeline: view()){
      @media (prefers-reduced-motion: no-preference){
        .module .rule-double{transform-origin:0 50%;animation:line-grow 1ms linear both;animation-timeline:view();animation-range:entry 0% entry 45%}
        .module .rule-double::after{animation:bead-pop 1ms linear both;animation-timeline:view();animation-range:entry 30% entry 70%}
        .sec-num{animation:lock-up 1ms linear both;animation-timeline:view();animation-range:entry 5% entry 45%}
        .kicker{animation:slide-in-neg 1ms linear both;animation-timeline:view();animation-range:entry 15% entry 55%}
        h2.sec-title{animation:lock-up 1ms linear both;animation-timeline:view();animation-range:entry 15% entry 60%}
        .sec-lead{animation:lock-up-soft 1ms linear both;animation-timeline:view();animation-range:entry 25% entry 70%}
        .dropcap{animation:stamp-view-flat 1ms linear both;animation-timeline:view();animation-range:entry 20% entry 65%}
        .code-plate,.pullframe,.triple,.figure-plate{animation:lock-up-soft 1ms linear both;animation-timeline:view();animation-range:entry 10% entry 60%}
        .figure-plate .figrow{animation:lock-up-soft 1ms linear both;animation-timeline:view()}
        .figure-plate .figrow:nth-of-type(1){animation-range:entry 0% entry 45%}
        .figure-plate .figrow:nth-of-type(2){animation-range:entry 15% entry 60%}
        .figure-plate .figrow:nth-of-type(3){animation-range:entry 30% entry 75%}
        .figure-plate .figrow .tickband{animation:tick-lay 1ms linear both;animation-timeline:view()}
        .figure-plate .figrow:nth-of-type(1) .tickband{animation-range:entry 0% entry 45%}
        .figure-plate .figrow:nth-of-type(2) .tickband{animation-range:entry 15% entry 60%}
        .figure-plate .figrow:nth-of-type(3) .tickband{animation-range:entry 30% entry 75%}
        @keyframes tick-lay{from{clip-path:inset(-8px 100% -8px 0)}to{clip-path:inset(-8px 0% -8px 0)}}
        .notecards .notecard{animation:lock-up-soft 1ms linear both;animation-timeline:view()}
        .notecards .notecard:nth-child(1){animation-range:entry 10% entry 55%}
        .notecards .notecard:nth-child(2){animation-range:entry 25% entry 70%}
        .notecards .notecard:nth-child(3){animation-range:entry 40% entry 85%}
        .spread{animation:roller 1ms linear both;animation-timeline:view();animation-range:entry 0% cover 35%}
        .spread .seal-mini{animation:stamp-view-flat 1ms linear both;animation-timeline:view();animation-range:entry 60% cover 30%}
        .ghost-sun{animation:sun-turn 1ms linear both;animation-timeline:view();animation-range:entry 10% cover 30%}
        .end-band{animation:roller 1ms linear both;animation-timeline:view();animation-range:entry 0% entry 80%}
        .end-band .seal{animation:stamp-view-tilt 1ms linear both;animation-timeline:view();animation-range:entry 15% entry 90%}
        @keyframes line-grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
        @keyframes bead-pop{from{opacity:0;transform:translate(-50%,-50%) rotate(45deg) scale(0)}to{opacity:1;transform:translate(-50%,-50%) rotate(45deg) scale(1)}}
        @keyframes lock-up{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:none}}
        @keyframes lock-up-soft{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
        @keyframes slide-in-neg{from{opacity:0;transform:translateX(-10px)}to{opacity:1;transform:none}}
        @keyframes stamp-view-flat{0%{opacity:0;transform:scale(1.5) rotate(-8deg)}100%{opacity:1;transform:none}}
        @keyframes stamp-view-tilt{0%{opacity:0;transform:scale(1.5) rotate(-12deg)}100%{opacity:1;transform:rotate(-4deg)}}
        @keyframes roller{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}
      }
    }
    @supports (animation-timeline: scroll()){
      @media (prefers-reduced-motion: no-preference){
        #reading-progress{animation:progress-grow linear both;animation-timeline:scroll(root)}
        @keyframes progress-grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
      }
    }

    /* ---- v6 motion refinements: sequences & layers ---- */
    .kicker::after{transform-origin:0 50%}
    @media (prefers-reduced-motion: no-preference){
      .orn-row{animation:fade-in .8s ease .58s both}
      .reg{animation:fade-in 1.1s ease .3s both}
    }
    @supports (animation-timeline: view()){
      @media (prefers-reduced-motion: no-preference){
        .kicker::after{animation:line-grow 1ms linear both;animation-timeline:view();animation-range:entry 20% entry 60%}
        .kicker .numseal{animation:stamp-view-tilt 1ms linear both;animation-timeline:view();animation-range:entry 8% entry 48%}
        .deck-list li{animation:lock-up-soft 1ms linear both;animation-timeline:view()}
        .deck-list li:nth-child(1){animation-range:entry 0% entry 40%}
        .deck-list li:nth-child(2){animation-range:entry 10% entry 50%}
        .deck-list li:nth-child(3){animation-range:entry 20% entry 60%}
        .deck-list li:nth-child(4){animation-range:entry 30% entry 70%}
        .breakout tbody tr{animation:lock-up-soft 1ms linear both;animation-timeline:view()}
        .breakout tbody tr:nth-child(1){animation-range:entry 10% entry 50%}
        .breakout tbody tr:nth-child(2){animation-range:entry 20% entry 60%}
        .breakout tbody tr:nth-child(3){animation-range:entry 30% entry 70%}
        .q-text .ql{animation:lock-up 1ms linear both;animation-timeline:view()}
        .q-text .ql:nth-child(1){animation-range:entry 5% entry 45%}
        .q-text .ql:nth-child(2){animation-range:entry 22% entry 62%}
        .notecard .tag-seal{animation:stamp-view-flat 1ms linear both;animation-timeline:view();animation-range:entry 30% cover 25%}
        @keyframes sun-turn{from{opacity:0;transform:rotate(-70deg) scale(.88)}to{opacity:1;transform:none}}
      }
    }

    /* ---- registration marks: 印刷对位线 ---- */
    .reg{position:absolute;width:16px;height:16px;pointer-events:none;opacity:.4;z-index:4}
    .reg::before,.reg::after{content:"";position:absolute;background:#ece2cb}
    .reg::before{left:50%;top:0;width:1.5px;height:100%;transform:translateX(-50%)}
    .reg::after{top:50%;left:0;height:1.5px;width:100%;transform:translateY(-50%)}
    .reg.tl{top:16px;left:16px}.reg.tr{top:16px;right:16px}
    .reg.bl{bottom:16px;left:16px}.reg.br{bottom:16px;right:16px}

    /* ---- v7: organic layer motion ---- */
    @media (prefers-reduced-motion: no-preference){
      .branch.c1 svg{animation:sprout 1.3s var(--ease-out) .5s both}
      @keyframes sprout{from{opacity:0;transform:rotate(30deg) scale(.9)}to{opacity:1;transform:none}}
    }
    @supports (animation-timeline: view()){
      @media (prefers-reduced-motion: no-preference){
        .branch.c2 svg,.branch.c3 svg{transform-origin:50% 95%;animation:sprout-view 1ms linear both;animation-timeline:view()}
        .branch.c2 svg{animation-range:entry 10% cover 35%}
        .branch.c3 svg{animation-range:entry 0% entry 85%}
        @keyframes sprout-view{from{opacity:0;transform:rotate(40deg) scale(.9)}to{opacity:1;transform:none}}
      }
    }

    /* ---- v8: cover fan & extra branches ---- */
    @media (prefers-reduced-motion: no-preference){
      .cover-fan{animation:fan-in 1.8s var(--ease-out) .05s both}
      .orn-row .seal-mini{animation:stamp-flat .45s var(--ease-stamp) 1s both}
      .branch.c1b svg{animation:sprout 1.3s var(--ease-out) .8s both;transform-origin:80% 10%}
      @keyframes fan-in{from{opacity:0;transform:translateX(-50%) rotate(-14deg) scale(.94)}to{opacity:1;transform:translateX(-50%) rotate(0) scale(1)}}
    }
    @supports (animation-timeline: view()){
      @media (prefers-reduced-motion: no-preference){
        .branch.c4 svg{transform-origin:50% 90%;animation:sprout-view 1ms linear both;animation-timeline:view();animation-range:entry 15% cover 30%}
      }
    }
    @media (max-width: 860px){
      .cover-fan{left:22px;right:22px;width:auto;transform:none;top:96px;animation:none;opacity:1}
      .branch.c1b,.branch.c4{display:none}
    }

    /* ---- v11: ghost numeral entrance ---- */
    @supports (animation-timeline: view()){
      @media (prefers-reduced-motion: no-preference){
        .ghost-num{animation:fade-in 1ms linear both;animation-timeline:view();animation-range:entry 10% cover 30%}
        .triple .cell{animation:lock-up-soft 1ms linear both;animation-timeline:view()}
        .triple .cell:nth-child(1){animation-range:entry 0% entry 50%}
        .triple .cell:nth-child(2){animation-range:entry 15% entry 65%}
        .triple .cell:nth-child(3){animation-range:entry 30% entry 80%}
        .compare .cmp-card:nth-of-type(1){animation:lock-up-soft 1ms linear both;animation-timeline:view();animation-range:entry 5% entry 50%}
        .compare .cmp-divider{animation:fade-in 1ms linear both;animation-timeline:view();animation-range:entry 25% entry 65%}
        .compare .cmp-card:nth-of-type(2){animation:lock-up-soft 1ms linear both;animation-timeline:view();animation-range:entry 30% entry 75%}
        .takeaway{animation:lock-up-soft 1ms linear both;animation-timeline:view();animation-range:entry 35% entry 80%}
        .spread .q-note{animation:lock-up-soft 1ms linear both;animation-timeline:view();animation-range:entry 45% cover 20%}
        .spread .q-attr{animation:lock-up-soft 1ms linear both;animation-timeline:view();animation-range:entry 55% cover 30%}
      }
    }

    /* production utilities */
    .sr-first-char{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
    .sec-num-label{font-size:64px;line-height:1.05;padding-top:6px}
    .breakout .fig-kicker{color:var(--accent);opacity:.85}
    .dropcap{user-select:none}
"""

MAIN_SCRIPT = """
  <script>
    const progressBar = document.getElementById('reading-progress');
    function updateReadingProgress() {
      if (!progressBar) { return; }
      const winScroll = document.body.scrollTop || document.documentElement.scrollTop;
      const height = document.documentElement.scrollHeight - document.documentElement.clientHeight;
      const progress = height > 0 ? winScroll / height : 0;
      progressBar.style.transform = 'scaleX(' + Math.min(1, Math.max(0, progress)) + ')';
    }
    window.addEventListener('DOMContentLoaded', updateReadingProgress);
    window.addEventListener('scroll', updateReadingProgress, { passive: true });
  </script>
"""

MATHJAX_TEMPLATE = """
  <script>
    window.MathJax = {
      tex: {
        inlineMath: [['$','$'], ['\\\\(','\\\\)']],
        displayMath: [['$$','$$'], ['\\\\[','\\\\]']],
        processEscapes: true,
        processEnvironments: true,
        tags: 'ams'
      },
      svg: { fontCache: 'global', scale: 1, minScale: 0.5,
             linebreaks: { automatic: false }, mtextInheritFont: true, merrorInheritFont: true },
      options: { skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'] }
    };
  </script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
"""


def render_cover(data, reading_minutes):
    title = esc(data.get("title", "长输出"))
    # break the display title after a clause mark so CJK line breaks stay word-safe
    for mark in ("，", "；", "：", ", ", "; "):
        if mark in title and len(title) <= 24:
            title = title.replace(mark, mark + "<br/>", 1)
            break
    subtitle = str(data.get("subtitle") or "").strip()
    standfirst = esc(subtitle).replace("\n", "<br/>") if subtitle else ""
    tags = tag_html(data.get("tags"))
    seal_char = str(data.get("seal") or (data.get("title") or "读").strip()[:1] or "读")
    fan_svg = fan()
    sun_svg = sunburst()
    branch = branch_path()
    return f"""
<div class="cover-wrap">
<div class="top-rule" aria-hidden="true"></div>
<header class="cover shell">
  <span class="reg tl" aria-hidden="true"></span><span class="reg tr" aria-hidden="true"></span><span class="reg bl" aria-hidden="true"></span><span class="reg br" aria-hidden="true"></span>
  <div class="ghost" aria-hidden="true">{esc(seal_char)}</div>
  <div class="branch c1" aria-hidden="true">{branch}</div>
  <div class="cover-meta">
    <div>{esc(data.get("generated_at_display", ""))} · 全文约 {reading_minutes} 分钟</div>
    <div class="seal">{esc(seal_char)}</div>
  </div>
  <div class="cover-fan" aria-hidden="true">{fan_svg}</div>
  <div class="sunmark" style="margin-top:44px" aria-hidden="true">{sun_svg}</div>
  <h1 class="title">{title}</h1>
  {f'<p class="standfirst">{standfirst}</p>' if standfirst else ''}
  <div class="orn-row"><span class="ol"></span><span class="od"></span><span class="or"></span><span class="seal-mini">{esc(seal_char)}</span></div>
  <div class="branch c1b" aria-hidden="true">{branch}</div>
  {tags}
</header>
</div>"""


def render_deck(summary):
    if not summary:
        return ""
    deck = list_items(summary)
    return f"""
  <section class="module module-deck" style="padding-top:52px">
    <div class="rule-double"></div>
    <div class="mgrid">
      <div class="sec-num sec-num-label">导读</div>
      <div>
        <div class="kicker">本篇脉络</div>
        {deck}
      </div>
    </div>
  </section>"""


def render_body_section(section, index):
    title = esc(section.get("title", "未命名栏目"))
    lead = str(section.get("lead") or "").strip()
    kicker = str(section.get("kicker") or "").strip()
    content = add_drop_cap(markdown_to_html(str(section.get("content") or "")))
    for num in reversed(section.get("_table_range") or []):
        marker = "<div class=\"table-wrap\">"
        replacement = f'<div class="table-wrap">{table_label(num)}'
        # replace from the last occurrence backwards keeps numbering in order
        pos = content.rfind(marker)
        if pos != -1:
            content = content[:pos] + replacement + content[pos + len(marker):]
    notes = normalize_notes(section.get("notes"))
    kicker_html = (
        f'<div class="kicker k-seal"><span class="numseal">{cn_num(index)}</span>{esc(kicker)}</div>'
        if kicker
        else ""
    )
    notes_html = ""
    if notes:
        cards = "".join(
            f"""<div class="notecard">
              <div class="notecard-head"><span class="tag-seal">注</span><span class="notecard-label">{esc(n['label'])}</span></div>
              <div class="notecard-body">{markdown_to_html(n['content'])}</div>
            </div>"""
            for n in notes
        )
        notes_html = f'<div class="notecards">{cards}</div>'
    lead_html = f'<p class="sec-lead">{esc(lead)}</p>' if lead else ""
    return f"""
  <section class="module">
    <div class="rule-double"></div>
    <div class="mgrid">
      <div class="sec-num">{index:02d}</div>
      <div>
        {kicker_html}
        <h2 class="sec-title">{title}</h2>
        {lead_html}
        <div class="body-inner">{content}</div>
        {notes_html}
      </div>
    </div>
  </section>"""


def render_summary_section(section, index):
    title = esc(section.get("title") or "要点")
    intro = str(section.get("intro") or section.get("lead") or "").strip()
    items = normalize_text_items(section)
    cells = "".join(
        f"""<div class="cell"><div class="idx">{i:02d}</div>{f'<h3>{esc(item["title"])}</h3>' if item['title'] else ''}<p>{esc(item['text'])}</p></div>"""
        for i, item in enumerate(items, start=1)
    )
    kicker = str(section.get("kicker") or "要点")
    intro_html = f'<p class="sec-lead">{esc(intro)}</p>' if intro else ""
    return f"""
  <section class="module">
    <div class="ghost-num" aria-hidden="true">{index:02d}</div>
    <div class="rule-double"></div>
    <div class="mgrid">
      <div class="sec-num">{index:02d}</div>
      <div>
        <div class="kicker k-seal"><span class="numseal">{cn_num(index)}</span>{esc(kicker)}</div>
        <h2 class="sec-title">{title}</h2>
        {intro_html}
        <div class="triple">{cells}</div>
      </div>
    </div>
  </section>"""


def render_quote_section(section, sheet_in):
    text = str(section.get("content") or section.get("quote") or "").strip()
    note = str(section.get("note") or section.get("caption") or "").strip()
    attribution = str(section.get("attribution") or "").strip()
    kicker = str(section.get("kicker") or "引文")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        q_html = "".join(f'<span class="ql">{esc(ln)}</span>' for ln in lines)
    else:
        q_html = esc(text)
    note_html = f'<p class="q-note">{esc(note)}</p>' if note else ""
    attr_html = (
        f'<p class="q-attr">—— {esc(attribution)}<span class="seal-mini">印</span></p>'
        if attribution
        else '<p class="q-attr"><span class="seal-mini">印</span></p>'
    )
    return f"""{sheet_in}
<section class="spread">
  <div class="spread-inner">
    <div class="ghost-q" aria-hidden="true">「</div>
    <div class="ghost-sun" aria-hidden="true">{sunburst(size=130)}</div>
    <div class="kicker">{esc(kicker)}</div>
    <p class="q-text">{q_html}</p>
    {note_html}
    {attr_html}
  </div>
</section>"""


def render_compare_section(section, index):
    title = esc(section.get("title") or "对照")
    left = normalize_compare_side(section.get("left"), "方案 A")
    right = normalize_compare_side(section.get("right"), "方案 B")
    takeaway = str(section.get("takeaway") or "").strip()
    kicker = str(section.get("kicker") or "方案对照")

    def side_html(side):
        items = "".join(
            f"""<div class="cmp-item">{f'<div class="cmp-label">{esc(i["label"])}</div>' if i['label'] else ''}<div class="cmp-text">{esc(i['text'])}</div></div>"""
            for i in side["items"]
        )
        return f"""<article class="cmp-card"><div class="cmp-title">{esc(side['title'])}</div>{items}</article>"""

    takeaway_html = f'<p class="takeaway">{esc(takeaway)}</p>' if takeaway else ""
    return f"""
  <section class="module">
    <div class="rule-double"></div>
    <div class="mgrid">
      <div class="sec-num">{index:02d}</div>
      <div>
        <div class="kicker k-seal"><span class="numseal">{cn_num(index)}</span>{esc(kicker)}</div>
        <h2 class="sec-title">{title}</h2>
        <div class="compare">
          {side_html(left)}
          <div class="cmp-divider">对照</div>
          {side_html(right)}
        </div>
        {takeaway_html}
      </div>
    </div>
  </section>"""


def render_figure_section(section, index):
    fig = normalize_figure(section)
    if not fig:
        return ""
    kicker = str(section.get("kicker") or "图版")
    sub = f'<div class="fig-sub">{esc(fig["sub"])}</div>' if fig["sub"] else ""
    source = f'<div class="fig-src">{esc(fig["source"])}</div>' if fig["source"] else ""
    return f"""
  <section class="module">
    <div class="mgrid">
      <div></div>
      <div>
    <div class="figure-plate">
      <div class="fig-kicker">{esc(kicker)} · {cn_num(index)} &nbsp;&nbsp; FIGURE</div>
      <div class="fig-title">{esc(fig['title'])}</div>
      {sub}
      {render_tickrows(fig)}
      {source}
    </div>
      </div>
    </div>
  </section>"""


def build_default_output_path() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    return str(Path(DEFAULT_OUTPUT_DIR) / f"{DEFAULT_OUTPUT_PREFIX}-{timestamp}-{suffix}.html")


def render_sections(sections):
    """Render the section list, weaving cream quote sheets in and out with
    torn-paper boundaries so every colour change keeps the tear grammar."""
    blocks = []
    sheet_open = False
    for section in sections:
        stype = section["type"]
        index = section["_index"]
        if stype == "quote":
            blocks.append(render_quote_section(section, torn_edge(paper_above=True, seed=3)))
            sheet_open = True
            continue
        if sheet_open:
            blocks.append(torn_edge(paper_above=False, seed=9))
            sheet_open = False
        if stype == "figure":
            blocks.append(render_figure_section(section, index))
        elif stype == "summary":
            blocks.append(render_summary_section(section, index))
        elif stype == "compare":
            blocks.append(render_compare_section(section, index))
        else:
            blocks.append(render_body_section(section, index))
    if sheet_open:
        blocks.append(torn_edge(paper_above=False, seed=9))
    return "".join(blocks)


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        raise SystemExit("Expected JSON on stdin")
    data = json.loads(raw)

    title = data.get("title", "长输出")
    subtitle = data.get("subtitle", "")
    summary = data.get("summary", [])
    sections = data.get("sections", [])
    appendix = data.get("appendix", [])
    tags = data.get("tags", [])
    body_variant = normalize_body_variant(data.get("body_variant"), "narrative")
    theme = str(data.get("theme") or "green").strip().lower()
    if theme not in SUPPORTED_THEMES:
        theme = "green"
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
    total_chars = len(re.sub(r"\s+", "", raw_search))
    reading_minutes = max(1, total_chars // 300) if total_chars else 1
    math_enabled = bool(data.get("math")) or bool(
        re.search(r"\$\$|\\\(|\\\)|\\\[|\\\]|\\begin\{", raw_search)
    )
    mathjax_html = MATHJAX_TEMPLATE if math_enabled else ""

    normalized = []
    for i, section in enumerate(sections or [], start=1):
        section = normalize_section(section, body_variant)
        section["_index"] = i
        section["_table_range"] = []
        normalized.append(section)

    # 表版 numbering: count tables per body section in document order
    table_counter = 0
    for section in normalized:
        if section["type"] != "body":
            continue
        count = len(TABLE_WRAP_RE.findall(markdown_to_html(str(section.get("content") or ""))))
        if count:
            section["_table_range"] = list(range(table_counter + 1, table_counter + count + 1))
            table_counter += count

    cover_html = render_cover(
        {
            "title": title,
            "subtitle": subtitle,
            "tags": tags,
            "generated_at_display": display_date,
        },
        reading_minutes,
    )
    deck_html = render_deck(summary)
    articles_html = render_sections(normalized)

    html_doc = f"""<!doctype html>
<html lang="zh-CN" data-theme="{theme}">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{esc(title)}</title>
  <style>{CSS_BASE}{build_pygments_css()}
  </style>
</head>
<body>
<div id="reading-progress"></div>
{cover_html}
<main class="shell">
{deck_html}{articles_html}
</main>
{torn_edge(paper_above=True, seed=11)}
<div class="end-band">
  <div class="band-inner">
    <div class="sunmark" aria-hidden="true">{sunburst()}</div>
    <div class="seal">完</div>
    <div class="end-meta">{esc(display_date)} · 全文约 {reading_minutes} 分钟</div>
  </div>
</div>
{MAIN_SCRIPT}
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
