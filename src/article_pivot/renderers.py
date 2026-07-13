from __future__ import annotations

from .model import Block, InlineNode, TranslationOverlay
from .package import CanonicalPackage
from .publication import PublicationDocument, build_publication_document
from .validation import validate_document


def render_inlines(nodes: tuple[InlineNode, ...]) -> str:
    rendered: list[str] = []
    for node in nodes:
        child_text = render_inlines(node.children) if node.children else node.text
        if node.type == "text":
            rendered.append(child_text)
        elif node.type == "strong":
            rendered.append(f"**{child_text}**")
        elif node.type == "emphasis":
            rendered.append(f"*{child_text}*")
        elif node.type == "inline_code":
            rendered.append(f"`{child_text}`")
        elif node.type == "inline_math":
            rendered.append(f"${child_text}$")
        elif node.type == "link":
            rendered.append(f"[{child_text}]({node.attrs.get('url', '')})")
        elif node.type == "line_break":
            rendered.append("  \n")
        else:
            rendered.append(child_text)
    return "".join(rendered)


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def _render_block(block: Block, heading_offset: int, in_quote: bool = False) -> str:
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
        return f"$$\n{block.attrs['latex']}\n$$"
    if block.type == "image":
        return f"![{block.attrs.get('alt', '')}]({block.attrs.get('url', '')})"
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
        lines = []
        for index, child in enumerate(block.children, start=1):
            marker = f"{index}." if ordered else "•" if in_quote else "-"
            lines.append(f"{marker} {render_inlines(child.inlines)}")
        return "\n".join(lines)
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
    if translated is None or original.type in {"code", "math", "image", "divider"}:
        return [_render_block(original, 2)]
    translated_text = _render_block(translated, 2)
    original_text = _render_block(original, 2)
    if original.type == "heading":
        return [translated_text, _quote(render_inlines(original.inlines))]
    if original.type == "list":
        quoted = "\n".join(
            f"> • {line.split(' ', 1)[1]}" if " " in line else f"> • {line}"
            for line in original_text.splitlines()
        )
        return [translated_text, quoted]
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
                original = "\n".join(
                    f"> • {line.split(' ', 1)[1]}" if " " in line else f"> • {line}"
                    for line in original.splitlines()
                )
                parts.append(original)
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
        f"# {package.document.title}",
        _quote(
            f"来源：Lil'Log / {source.get('author', 'Lilian Weng')}，{published}\n"
            f"原文链接：{source.get('canonical_url', '')}"
        ),
    ]
    parts.extend(_render_block(block, heading_offset) for block in package.document.blocks)
    return "\n\n".join(part for part in parts if part).rstrip() + "\n"
