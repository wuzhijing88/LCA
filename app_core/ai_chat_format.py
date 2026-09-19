"""Format AI chat text: fenced blocks become copyable boxes."""

from __future__ import annotations

import html
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

FENCE_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<mark>`{3,}|~{3,})(?P<info>[^\n]*)\n"
    r"(?P<body>.*?)(?:^[ \t]*(?P=mark)[ \t]*(?:\n|\Z)|\Z)",
    re.MULTILINE | re.DOTALL,
)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)([^*\n]+?)(?<!\*)\*(?!\*)")
STRIKE_RE = re.compile(r"~~(.+?)~~")
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
UL_RE = re.compile(r"^[-*+]\s+(.+)$")
OL_RE = re.compile(r"^(\d+)\.\s+(.+)$")
HR_RE = re.compile(r"^(?:---|\*\*\*|___)\s*$")
QUOTE_RE = re.compile(r"^>\s?(.*)$")
TABLE_SEP_CELL_RE = re.compile(r"^:?-+:?$")
_HEADING_SIZE = {1: 18, 2: 16, 3: 15, 4: 14, 5: 13, 6: 13}
WORKFLOW_FENCE_LANGUAGE = "工作流"
_BLOCK_LABELS = {
    "md": "Markdown",
    "markdown": "Markdown",
    "mermaid": "思维导图",
    "mindmap": "思维导图",
    "lca": "自定义脚本",
    "自定义脚本": "自定义脚本",
    WORKFLOW_FENCE_LANGUAGE: "工作流",
}
_PYTHON_TAGS = {"python", "py", "python3"}
_GENERIC_TAGS = {"", "text", "txt", "plain", "plaintext"}
_LCA_SCRIPT_MARKERS = (
    "等图(",
    "找图(",
    "点击(",
    "延时(",
    "失败(",
    "成功(",
    "记录(",
    "点文字(",
    "找字(",
    "检测(",
    "如果 ",
    "否则:",
    "否则如果 ",
    "循环 ",
    "子程序 ",
    "变量.",
    "数据.",
    "定时器.",
)


def fence_language(info: str) -> str:
    token = str(info or "").strip()
    if not token:
        return ""
    return token.split()[0].strip()


def looks_like_lca_script(body: str) -> bool:
    text = str(body or "")
    return any(marker in text for marker in _LCA_SCRIPT_MARKERS)


def _normalize_newlines(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def _dedent_prefixed_lines(text: str, indent: str) -> str:
    if not indent:
        return text
    lines = str(text or "").split("\n")
    out: List[str] = []
    for line in lines:
        if line.startswith(indent):
            out.append(line[len(indent):])
            continue
        if not line.strip():
            out.append("")
            continue
        index = 0
        limit = min(len(line), len(indent))
        while index < limit and line[index] in " \t":
            index += 1
        out.append(line[index:])
    return "\n".join(out)


def _leading_width(line: str) -> int:
    width = 0
    for char in line:
        if char == " ":
            width += 1
        elif char == "\t":
            width += 4
        else:
            break
    return width


def block_label(language: str, body: str = "") -> str:
    key = str(language or "").strip()
    mapped = _BLOCK_LABELS.get(key.lower())
    if mapped:
        return mapped
    generic = key.lower() in _GENERIC_TAGS
    if looks_like_lca_script(body) and (generic or key.lower() in _PYTHON_TAGS):
        return "自定义脚本"
    if generic:
        return "代码"
    return key


def iter_message_segments(text: str) -> Iterable[Tuple[str, str, str]]:
    source = _normalize_newlines(text)
    cursor = 0
    for match in FENCE_RE.finditer(source):
        start = match.start()
        if start > cursor:
            yield ("text", "", source[cursor:start])
        body = match.group("body")
        if body.endswith("\n"):
            body = body[:-1]
        body = _dedent_prefixed_lines(body, match.group("indent") or "")
        yield ("fence", fence_language(match.group("info")), body)
        cursor = match.end()
    if cursor < len(source):
        yield ("text", "", source[cursor:])
    elif not source:
        yield ("text", "", "")


def _format_inline(text: str) -> str:
    source = str(text or "")
    codes: List[str] = []
    links: List[Tuple[str, str]] = []

    def _stash_code(match: re.Match[str]) -> str:
        codes.append(html.escape(match.group(1)))
        return f"@@CODE{len(codes) - 1}@@"

    def _stash_link(match: re.Match[str]) -> str:
        links.append((match.group(1), match.group(2)))
        return f"@@LINK{len(links) - 1}@@"

    protected = INLINE_CODE_RE.sub(_stash_code, source)
    protected = LINK_RE.sub(_stash_link, protected)
    escaped = html.escape(protected)

    def _bold(match: re.Match[str]) -> str:
        return f"<b>{match.group(1) or match.group(2)}</b>"

    def _italic(match: re.Match[str]) -> str:
        return f"<i>{match.group(1)}</i>"

    def _strike(match: re.Match[str]) -> str:
        return f"<s>{match.group(1)}</s>"

    escaped = BOLD_RE.sub(_bold, escaped)
    escaped = STRIKE_RE.sub(_strike, escaped)
    escaped = ITALIC_RE.sub(_italic, escaped)
    for index, (label, href) in enumerate(links):
        escaped = escaped.replace(
            f"@@LINK{index}@@",
            f"<a href='{html.escape(href, quote=True)}'>{html.escape(label)}</a>",
        )
    for index, code in enumerate(codes):
        escaped = escaped.replace(
            f"@@CODE{index}@@",
            "<span style='font-family: Consolas, \"Courier New\", monospace;"
            " background-color:@@INLINE_BG@@; padding-top:1px; padding-bottom:1px;"
            f" padding-left:4px; padding-right:4px;'>{code}</span>",
        )
    return escaped


def _is_table_row(line: str) -> bool:
    text = line.strip()
    return text.startswith("|") and text.count("|") >= 2


def _is_table_separator(line: str) -> bool:
    if not _is_table_row(line):
        return False
    cells = _table_cells(line)
    return bool(cells) and all(TABLE_SEP_CELL_RE.match(cell.replace(" ", "")) for cell in cells)


def _table_cells(line: str) -> List[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _consume_table(lines: Sequence[str], start: int) -> Tuple[int, List[List[str]]] | None:
    if start + 1 >= len(lines):
        return None
    header = lines[start].rstrip()
    separator = lines[start + 1].rstrip()
    if not _is_table_row(header) or not _is_table_separator(separator):
        return None
    rows = [_table_cells(header)]
    index = start + 2
    while index < len(lines):
        row = lines[index].rstrip()
        if not _is_table_row(row) or _is_table_separator(row):
            break
        rows.append(_table_cells(row))
        index += 1
    return index, rows


def _table_html(rows: Sequence[Sequence[str]], colors: Dict[str, str]) -> str:
    if not rows:
        return ""
    border = colors["border"]
    text = colors["text"]
    surface = colors["surface"]
    canvas = colors["canvas"]
    parts = [
        f"<table width='100%' cellspacing='0' cellpadding='6' "
        f"style='margin-top:8px; margin-bottom:8px; margin-left:0px; margin-right:0px; "
        f"border-collapse:collapse; color:{text};'>"
    ]
    for row_index, row in enumerate(rows):
        bg = surface if row_index == 0 else canvas
        tag = "th" if row_index == 0 else "td"
        weight = "700" if row_index == 0 else "400"
        parts.append("<tr>")
        for cell in row:
            parts.append(
                f"<{tag} bgcolor='{bg}' style='border:1px solid {border}; "
                f"font-weight:{weight}; text-align:left;'>{_format_inline(cell)}</{tag}>"
            )
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


def _quote_html(lines: Sequence[str], colors: Dict[str, str]) -> str:
    accent = colors["accent"]
    surface = colors["surface"]
    text = colors["text"]
    body = "<br/>".join(_format_inline(line) for line in lines)
    return (
        f"<table width='100%' cellspacing='0' cellpadding='0' "
        f"style='margin-top:8px; margin-bottom:8px; margin-left:0px; margin-right:0px;'>"
        f"<tr><td width='4' bgcolor='{accent}'></td>"
        f"<td bgcolor='{surface}' style='padding-top:6px; padding-bottom:6px; "
        f"padding-left:10px; padding-right:10px; color:{text};'>{body}</td>"
        f"</tr></table>"
    )


def _p(
    content: str,
    colors: Dict[str, str],
    *,
    top: int,
    bottom: int,
    left: int = 0,
) -> str:
    return (
        f"<p style='margin-top:{top}px; margin-bottom:{bottom}px; "
        f"margin-left:{left}px; margin-right:0px; color:{colors['text']};'>"
        f"{content}</p>"
    )


def _format_prose(text: str, colors: Dict[str, str]) -> str:
    source = _normalize_newlines(text)
    if not source.strip():
        return ""
    text_color = colors["text"]
    border = colors["border"]
    lines = source.split("\n")
    parts: List[str] = []
    index = 0

    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        table = _consume_table(lines, index)
        if table:
            nxt, rows = table
            parts.append(_table_html(rows, colors))
            index = nxt
            continue
        quotes: List[str] = []
        while index < len(lines):
            quote = QUOTE_RE.match(lines[index].rstrip().strip())
            if not quote:
                break
            quotes.append(quote.group(1))
            index += 1
        if quotes:
            parts.append(_quote_html(quotes, colors))
            continue
        heading = HEADING_RE.match(stripped)
        if heading:
            level = min(6, len(heading.group(1)))
            size = _HEADING_SIZE[level]
            title = _format_inline(heading.group(2).strip())
            top = 16 if level <= 2 else 12
            parts.append(
                f"<h{level} style='margin-top:{top}px; margin-bottom:6px; "
                f"margin-left:0px; margin-right:0px; font-weight:700; font-size:{size}px; "
                f"color:{text_color};'>{title}</h{level}>"
            )
            index += 1
            continue
        if HR_RE.match(stripped):
            parts.append(
                f"<hr style='border:none; border-top:1px solid {border}; "
                f"margin-top:12px; margin-bottom:12px; margin-left:0px; margin-right:0px;' />"
            )
            index += 1
            continue
        unordered = UL_RE.match(stripped)
        if unordered:
            left = 8 + _leading_width(line) * 8
            parts.append(
                _p(
                    f"• {_format_inline(unordered.group(1))}",
                    colors,
                    top=2,
                    bottom=2,
                    left=left,
                )
            )
            index += 1
            continue
        ordered = OL_RE.match(stripped)
        if ordered:
            left = _leading_width(line) * 8
            parts.append(
                _p(
                    f"{ordered.group(1)}. {_format_inline(ordered.group(2))}",
                    colors,
                    top=2,
                    bottom=2,
                    left=left,
                )
            )
            index += 1
            continue
        if not stripped:
            index += 1
            continue
        parts.append(_p(_format_inline(line), colors, top=0, bottom=8))
        index += 1
    html_text = "".join(parts)
    return html_text.replace("@@INLINE_BG@@", colors["surface"])


def _block_html(index: int, language: str, body: str, colors: Dict[str, str]) -> str:
    label = html.escape(block_label(language, body))
    payload = html.escape(body)
    surface = colors["surface"]
    canvas = colors["canvas"]
    border = colors["border"]
    muted = colors["muted"]
    accent = colors["accent"]
    text = colors["text"]
    actions = []
    if str(language or "").strip() == WORKFLOW_FENCE_LANGUAGE:
        actions.append(
            f"<a href='apply:{index}' style='color:{accent}; text-decoration:none;'>应用</a>"
        )
        actions.append(
            f"<a href='download:{index}' style='color:{accent}; text-decoration:none;'>下载</a>"
        )
    actions.append(
        f"<a href='copy:{index}' style='color:{accent}; text-decoration:none;'>复制</a>"
    )
    action_html = "&nbsp;&nbsp;".join(actions)
    return (
        f"<table width='100%' cellspacing='0' cellpadding='0' "
        f"style='margin-top:8px; margin-bottom:8px; margin-left:0px; margin-right:0px; "
        f"border:1px solid {border};'>"
        f"<tr><td bgcolor='{surface}' style='padding-top:6px; padding-bottom:6px; "
        f"padding-left:8px; padding-right:8px;'>"
        f"<table width='100%' cellspacing='0' cellpadding='0'><tr>"
        f"<td style='color:{muted};'>{label}</td>"
        f"<td align='right'>{action_html}</td>"
        f"</tr></table></td></tr>"
        f"<tr><td bgcolor='{canvas}' style='padding-top:8px; padding-bottom:8px; "
        f"padding-left:8px; padding-right:8px;'>"
        f"<pre style='margin-top:0px; margin-bottom:0px; margin-left:0px; margin-right:0px; "
        f"color:{text}; font-family: Consolas, \"Courier New\", monospace;'>{payload}</pre>"
        f"</td></tr></table>"
    )


def format_ai_message_html(
    text: str,
    colors: Dict[str, str],
    *,
    start_index: int = 0,
) -> Tuple[str, List[str]]:
    """Return Qt rich-text HTML and copy payloads for fenced blocks."""
    payloads: List[str] = []
    parts: List[str] = []
    for kind, language, body in iter_message_segments(text):
        if kind == "fence":
            index = start_index + len(payloads)
            payloads.append(body)
            parts.append(_block_html(index, language, body, colors))
            continue
        formatted = _format_prose(body, colors)
        if formatted:
            parts.append(formatted)
    return "".join(parts), payloads


AI_IMAGE_THUMB_MAX = 96


def _file_url(path: str) -> str:
    normalized = os.path.abspath(path).replace("\\", "/")
    if len(normalized) >= 2 and normalized[1] == ":":
        return "file:///" + normalized
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return "file://" + normalized


def thumbnail_size(path: str, max_side: int = AI_IMAGE_THUMB_MAX) -> Tuple[int, int]:
    limit = max(1, int(max_side))
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
    except Exception:
        return limit, limit
    if width <= 0 or height <= 0:
        return limit, limit
    scale = min(limit / width, limit / height, 1.0)
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _images_html(images: Any, colors: Dict[str, str], image_paths: List[str]) -> str:
    if not isinstance(images, list) or not images:
        return ""
    parts: List[str] = []
    border = colors["border"]
    muted = colors["muted"]
    for item in images:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        if not os.path.isfile(path):
            parts.append(
                f"<p style='margin-top:0px; margin-bottom:8px; color:{muted};'>（图片已丢失）</p>"
            )
            continue
        index = len(image_paths)
        image_paths.append(path)
        width, height = thumbnail_size(path)
        url = html.escape(_file_url(path), quote=True)
        parts.append(
            f"<p style='margin-top:0px; margin-bottom:8px;'>"
            f"<a href='image:{index}'>"
            f"<img src='{url}' width='{width}' height='{height}' "
            f"style='border:1px solid {border};' />"
            f"</a></p>"
        )
    return "".join(parts)


def _files_html(files: Any, colors: Dict[str, str]) -> str:
    if not isinstance(files, list) or not files:
        return ""
    parts: List[str] = []
    muted = colors["muted"]
    text = colors["text"]
    border = colors["border"]
    for item in files:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "").strip()
        name = str(item.get("name") or "").strip() or os.path.basename(path) or "工作流文件"
        if not path or not os.path.isfile(path):
            parts.append(
                f"<p style='margin-top:0px; margin-bottom:8px; color:{muted};'>"
                f"（工作流文件已丢失：{html.escape(name)}）</p>"
            )
            continue
        parts.append(
            f"<p style='margin-top:0px; margin-bottom:8px; color:{text}; "
            f"border:1px solid {border}; padding:6px 8px;'>"
            f"附件：{html.escape(name)}</p>"
        )
    return "".join(parts)


def format_ai_thinking_html(text: str, colors: Dict[str, str], *, live: bool = False) -> str:
    if not live:
        return ""
    muted = colors["muted"]
    return (
        f"<p style='margin-top:0px; margin-bottom:8px; color:{muted};'>"
        f"{html.escape('正在查阅开源仓库…')}</p>"
    )


def format_ai_transcript_html(
    messages: Sequence[Mapping[str, Any]],
    colors: Dict[str, str],
) -> Tuple[str, List[str], List[str]]:
    if not messages:
        muted = colors["muted"]
        return (
            f"<p style='color:{muted};'>还没有对话。在下方输入问题后点发送。</p>",
            [],
            [],
        )
    payloads: List[str] = []
    image_paths: List[str] = []
    blocks = [f"<div style='color:{colors['text']};'>"]
    for item in messages:
        role = str(item.get("role") or "")
        label = "你" if role == "user" else "AI"
        color = colors["user"] if role == "user" else colors["assistant"]
        images_html = _images_html(item.get("images"), colors, image_paths)
        files_html = _files_html(item.get("files"), colors)
        body_html, copied = format_ai_message_html(
            str(item.get("content") or ""),
            colors,
            start_index=len(payloads),
        )
        payloads.extend(copied)
        blocks.append(
            f"<div style='margin:0 0 18px 0;'>"
            f"<p style='margin:0 0 8px 0;'><b style='color:{color};'>{html.escape(label)}</b></p>"
            f"{images_html}{files_html}{body_html}</div>"
        )
    blocks.append("</div>")
    return "".join(blocks), payloads, image_paths
