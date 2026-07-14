from __future__ import annotations

import re

from .model import Block, InlineNode, TranslationOverlay
from .package import CanonicalPackage
from .publication import PublicationDocument, build_publication_document
from .validation import validate_document


def render_inlines(nodes: tuple[InlineNode, ...]) -> str:
    def plain_text(node: InlineNode) -> str:
        return "".join(plain_text(child) for child in node.children) if node.children else node.text

    rendered: list[str] = []
    skip_leading_dollar = False
    for index, node in enumerate(nodes):
        child_text = render_inlines(node.children) if node.children else node.text
        if node.type == "text" and skip_leading_dollar:
            child_text = re.sub(r"^(\s*)\$", r"\1", child_text, count=1)
            skip_leading_dollar = False
        if node.type == "text":
            rendered.append(child_text)
        elif node.type == "strong":
            rendered.append(f"**{child_text}**")
        elif node.type == "emphasis":
            rendered.append(f"*{child_text}*")
        elif node.type == "inline_code":
            rendered.append(f"`{child_text}`")
        elif node.type == "inline_math":
            previous = nodes[index - 1] if index else None
            following = nodes[index + 1] if index + 1 < len(nodes) else None
            display_wrapped = (
                "\n" in child_text
                and previous is not None
                and previous.type == "text"
                and previous.text.rstrip().endswith("$")
                and following is not None
                and following.type == "text"
                and following.text.lstrip().startswith("$")
            )
            if display_wrapped:
                rendered[-1] = re.sub(r"\$(\s*)$", r"\1", rendered[-1], count=1)
                rendered.append(f"\n\n$$\n{normalize_display_math(child_text)}\n$$\n\n")
                skip_leading_dollar = True
            else:
                child_text = normalize_inline_math(child_text)
                symbol_word = (
                    child_text.strip() in {r"\epsilon", r"\varepsilon"}
                    and following is not None
                    and following.type == "text"
                    and following.text.startswith("-")
                )
                if symbol_word:
                    rendered.append("ε")
                    continue
                suffix = (
                    " "
                    if following is not None
                    and following.type == "text"
                    and following.text.startswith("-")
                    else ""
                )
                rendered.append(f"${re.sub(r'\s+', ' ', child_text.strip())}${suffix}")
        elif node.type == "link":
            label = "".join(plain_text(child) for child in node.children) or node.text
            url = node.attrs.get("url", "")
            rendered.append(f"[{label or url}]({url})")
        elif node.type == "line_break":
            rendered.append("  \n")
        else:
            rendered.append(child_text)
    return "".join(rendered)


def _quote(text: str) -> str:
    def quote_line(line: str) -> str:
        line = re.sub(r"^\s*[-*]\s+", "• ", line)
        return f"> {line}" if line.strip() else ">"

    return "\n".join(quote_line(line) for line in text.splitlines())


def _quote_list(block: Block) -> str:
    """Render quoted list items as text bullets that DingTalk keeps visible."""
    lines: list[str] = []

    def append_items(current: Block, depth: int = 0) -> None:
        bullet = "•" if depth == 0 else "◦"
        for child in current.children:
            lines.append(_quote(f"{bullet} {render_inlines(child.inlines)}"))
            for nested in child.children:
                if nested.type == "list":
                    append_items(nested, depth + 1)

    append_items(block)
    has_nested = any(child.children for child in block.children)
    return ("\n\n" if _has_inline_math(block) or has_nested else "\n").join(lines)


def _render_original_list(block: Block, heading_offset: int) -> str:
    if _has_inline_math(block):
        return "英文原文：\n\n" + _render_block(block, heading_offset)
    return _quote_list(block)


def is_pseudo_table(block: Block) -> bool:
    if block.type != "paragraph":
        return False
    lines = [line.strip() for line in render_inlines(block.inlines).splitlines()]
    rows = [line for line in lines if line and not line.startswith("{:")]
    return len(rows) >= 2 and all(line.startswith("|") and line.endswith("|") for line in rows)


def _render_pseudo_table(block: Block) -> str:
    rows = [
        line.strip()
        for line in render_inlines(block.inlines).splitlines()
        if line.strip() and not line.strip().startswith("{:")
    ]
    columns = max(1, rows[0].count("|") - 1)
    separator = "| " + " | ".join("---" for _ in range(columns)) + " |"
    if len(rows) == 1 or not re.fullmatch(r"\|(?:\s*:?-+:?\s*\|)+", rows[1]):
        rows.insert(1, separator)
    return "\n".join(rows)


def display_math_latex(block: Block) -> str | None:
    if block.type != "paragraph":
        return None
    nodes = tuple(
        node
        for node in block.inlines
        if node.type != "text" or node.text.strip()
    )
    if len(nodes) == 1 and nodes[0].type == "inline_math" and "\n" in nodes[0].text:
        return nodes[0].text.strip()
    if (
        len(nodes) == 3
        and nodes[0].type == "text"
        and nodes[0].text.strip() == "$"
        and nodes[1].type == "inline_math"
        and nodes[2].type == "text"
        and nodes[2].text.strip() == "$"
    ):
        return nodes[1].text.strip()
    return None


def normalize_display_math(latex: str) -> str:
    latex = latex.strip()
    latex = re.sub(r'\\textrm\{["“”]([^"“”]+)["“”]\}', r'\\text{\1}', latex)
    latex = latex.translate(str.maketrans("", "", '"“”'))
    if "\\xrightarrow[]{" in latex:
        latex = latex.replace("\\xrightarrow[]{", "\\xrightarrow[ ]{")
        return re.sub(r"\s*\n\s*", " ", latex)
    if re.search(r"(?m)^\s*-\d", latex):
        return re.sub(r"\s*\n\s*", " ", latex)
    return latex


def normalize_inline_math(latex: str) -> str:
    latex = re.sub(
        r"\^(\*+)",
        lambda match: "^{" + r"\ast" * len(match.group(1)) + "}",
        latex.strip(),
    )
    return re.sub(r"\s+", " ", latex)


def _has_inline_math(block: Block) -> bool:
    def node_has_math(node: InlineNode) -> bool:
        return node.type == "inline_math" or any(node_has_math(child) for child in node.children)

    return any(node_has_math(node) for node in block.inlines) or any(
        _has_inline_math(child) for child in block.children
    )


def _has_inline_type(block: Block, node_type: str) -> bool:
    def node_matches(node: InlineNode) -> bool:
        return node.type == node_type or any(node_matches(child) for child in node.children)

    return any(node_matches(node) for node in block.inlines) or any(
        _has_inline_type(child, node_type) for child in block.children
    )


def _render_block(block: Block, heading_offset: int, in_quote: bool = False) -> str:
    if is_pseudo_table(block):
        return _render_pseudo_table(block)
    display_latex = display_math_latex(block)
    if display_latex is not None:
        return f"$$\n{normalize_display_math(display_latex)}\n$$"
    text = render_inlines(block.inlines)
    if block.type == "heading":
        level = min(6, max(1, int(block.attrs["level"]) + heading_offset))
        return f"{'#' * level} {text}"
    if block.type == "paragraph":
        return text
    if block.type == "blockquote":
        body = "\n\n".join(_render_block(child, heading_offset, True) for child in block.children)
        return _quote(body or text)
    if block.type == "code":
        language = block.attrs.get("language", "")
        return f"```{language}\n{block.attrs['code']}\n```"
    if block.type == "math":
        return f"$$\n{normalize_display_math(block.attrs['latex'])}\n$$"
    if block.type == "image":
        alt = block.attrs.get("alt", "").replace("[", r"\[").replace("]", r"\]")
        return f"![{alt}]({block.attrs.get('url', '')})"
    if block.type == "table":
        headers = [str(value) for value in block.attrs.get("headers", [])]
        rows = [[str(value) for value in row] for row in block.attrs.get("rows", [])]
        if not headers and rows:
            headers = ["" for _ in rows[0]]
        if not headers:
            return ""
        escape = lambda value: value.replace("|", "\\|").replace("\n", "<br />")
        output = [
            "| " + " | ".join(escape(value) for value in headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        output.extend("| " + " | ".join(escape(value) for value in row) + " |" for row in rows)
        return "\n".join(output)
    if block.type == "list":
        ordered = bool(block.attrs.get("ordered"))
        paragraph_list = _has_inline_math(block)
        lines = []
        for index, child in enumerate(block.children, start=1):
            marker = (
                f"{index}\\."
                if ordered and paragraph_list
                else f"{index}."
                if ordered
                else "•"
                if paragraph_list or in_quote
                else "-"
            )
            lines.append(f"{marker} {render_inlines(child.inlines)}")
            for nested in child.children:
                nested_text = _render_block(nested, heading_offset, in_quote)
                indent = "" if _has_inline_math(nested) else "   "
                lines.extend(f"{indent}{line}" if line else "" for line in nested_text.splitlines())
        return ("\n\n" if paragraph_list else "\n").join(lines)
    if block.type == "divider":
        return "---"
    if block.children:
        return "\n\n".join(_render_block(child, heading_offset, in_quote) for child in block.children)
    return text


def _apply_overlay(block: Block, overlay: TranslationOverlay) -> Block:
    segment = overlay.segments.get(block.id)
    return Block(
        id=block.id,
        type=block.type,
        inlines=segment.inlines if segment else block.inlines,
        attrs=segment.attrs if segment and segment.attrs else block.attrs,
        children=tuple(_apply_overlay(child, overlay) for child in block.children),
    )


def _render_publication_entry(original: Block, translated: Block | None) -> list[str]:
    if (
        translated is None
        or original.type in {"code", "math", "image", "divider"}
        or display_math_latex(original) is not None
    ):
        return [_render_block(original, 2)]
    translated_text = _render_block(translated, 2)
    original_text = _render_block(original, 2)
    if original.type == "heading":
        return [translated_text, _quote(render_inlines(original.inlines))]
    if original.type == "list":
        return [translated_text, _render_original_list(original, 2)]
    if is_pseudo_table(original):
        return [translated_text, _quote(original_text)]
    if original.type == "blockquote":
        if _has_inline_math(original):
            translated_body = "\n\n".join(
                _render_block(child, 2) for child in translated.children
            )
            original_body = "\n\n".join(
                _render_block(child, 2) for child in original.children
            )
            return [
                "引用译文：\n\n" + translated_body,
                "英文原文：\n\n" + original_body,
            ]
        return [translated_text, original_text]
    if original.type == "paragraph" and _has_inline_math(original) and _has_inline_type(original, "strong"):
        simple_variable = (
            r"\$((?:[A-Za-z]|\\[A-Za-z]+)(?:_(?:\{[^{}]+\}|[A-Za-z0-9]))?)\$"
        )
        translated_text = re.sub(simple_variable, r"`\1`", translated_text)
        original_text = original_text.replace("**", "")
        original_text = re.sub(simple_variable, r"`\1`", original_text)
        original_text = re.sub(r"(?<!^)(?<!\n)(\$[^$\n]+\$)", r"\n\n\1", original_text)
        return [translated_text, "英文原文：" + original_text]
    return [translated_text, _quote(original_text)]


def render_publication_markdown(publication: PublicationDocument) -> str:
    metadata = _quote(
        f"来源：{publication.source_label}，{publication.published_date}\n"
        f"原文链接：{publication.source_url}\n"
        f"分类：{publication.category}"
    )
    parts = [
        f"# {publication.title}",
        _quote(publication.original_title),
        metadata,
        "## 核心要点",
        "\n".join(f"- {point}" for point in publication.key_points),
        "## 正文",
    ]
    for entry in publication.body:
        parts.extend(_render_publication_entry(entry.original, entry.translated))
    parts.extend(
        [
            "## 术语对照",
            "| 英文 | 中文 | 说明 |\n|---|---|---|\n"
            + "\n".join(
                "| "
                + " | ".join(
                    value.replace("|", "\\|").replace("\n", " ")
                    for value in (item.term, item.translation, item.note)
                )
                + " |"
                for item in publication.glossary
            ),
        ]
    )
    return "\n\n".join(part for part in parts if part).rstrip() + "\n"


def render_bilingual_markdown(
    package: CanonicalPackage,
    locale: str = "zh-CN",
    heading_offset: int = 1,
) -> str:
    if package.editorial(locale):
        return render_publication_markdown(build_publication_document(package, locale))
    overlay = package.translation(locale)
    validate_document(package.document, overlay).require_ok()
    title = overlay.title if overlay and overlay.title else package.document.title
    original_title = package.document.title_en or package.document.title
    parts = [f"# {title}"]
    if overlay and title != original_title:
        parts.append(_quote(original_title))
    for block in package.document.blocks:
        has_translation = overlay and any(item.id in overlay.segments for item in block.walk())
        if has_translation and block.type not in {"code", "math", "image", "divider"}:
            translated_block = _apply_overlay(block, overlay)
            parts.append(_render_block(translated_block, heading_offset))
            original = _render_block(block, heading_offset)
            if block.type == "heading":
                parts.append(_quote(render_inlines(block.inlines)))
            elif block.type == "list":
                parts.append(_render_original_list(block, heading_offset))
            else:
                parts.append(_quote(original))
        else:
            parts.append(_render_block(block, heading_offset))
    return "\n\n".join(part for part in parts if part).rstrip() + "\n"


def render_source_markdown(package: CanonicalPackage, heading_offset: int = 1) -> str:
    validate_document(package.document).require_ok()
    source = package.document.source
    published = str(source.get("published_at", ""))[:10]
    parts = [
        f"# {package.document.title_en or package.document.title}",
        _quote(
            f"来源：Lil'Log / {source.get('author', 'Lilian Weng')}，{published}\n"
            f"原文链接：{source.get('canonical_url', '')}"
        ),
    ]
    parts.extend(_render_block(block, heading_offset) for block in package.document.blocks)
    return "\n\n".join(part for part in parts if part).rstrip() + "\n"
