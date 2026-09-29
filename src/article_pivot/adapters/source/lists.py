"""Ordered-list helpers shared by HTML source adapters.

Some publishers emit one ``<ol start="N">`` per step instead of a single list
with N items. Dropping ``start`` makes every step render as "1.", so keep it on
the block and re-join runs whose numbering is contiguous, which restores a
single ordered list for downstream renderers.
"""

from __future__ import annotations

from collections.abc import Sequence

from bs4 import Tag

from ...model import Block


def list_attrs(name: str, element: Tag) -> dict[str, object]:
    """Build list block attrs, preserving an explicit non-default ``start``."""
    attrs: dict[str, object] = {"ordered": name == "ol"}
    if name != "ol":
        return attrs
    start = _int_or_none(element.get("start"))
    if start is None or start == 1:
        return attrs
    return {**attrs, "start": start}


def merge_adjacent_ordered_lists(blocks: Sequence[Block]) -> tuple[Block, ...]:
    """Join sibling ordered lists that continue each other's numbering."""
    merged: list[Block] = []
    for block in blocks:
        previous = merged[-1] if merged else None
        if previous is not None and _continues(previous, block):
            merged[-1] = Block(
                id=previous.id,
                type=previous.type,
                inlines=previous.inlines,
                attrs=dict(previous.attrs),
                children=previous.children + block.children,
            )
            continue
        merged.append(block)
    return tuple(merged)


def _continues(previous: Block, block: Block) -> bool:
    if previous.type != "list" or block.type != "list":
        return False
    if not previous.attrs.get("ordered") or not block.attrs.get("ordered"):
        return False
    expected = _int_or_none(previous.attrs.get("start")) or 1
    return _int_or_none(block.attrs.get("start")) == expected + len(previous.children)


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
