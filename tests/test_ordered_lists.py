from __future__ import annotations

import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from article_pivot.adapters.source.lists import list_attrs, merge_adjacent_ordered_lists
from article_pivot.model import Block, InlineNode
from article_pivot.renderers import _render_original_list, render_source_markdown
from article_pivot.model import CanonicalDocument
from article_pivot.package import CanonicalPackage


def _ol(html: str):
    return BeautifulSoup(html, "html.parser").find("ol")


def _list(block_id: str, start: int | None, labels: list[str]) -> Block:
    attrs: dict[str, object] = {"ordered": True}
    if start is not None:
        attrs["start"] = start
    return Block(
        block_id,
        "list",
        attrs=attrs,
        children=tuple(
            Block(f"{block_id}i{index}", "list_item", (InlineNode("text", text=label),))
            for index, label in enumerate(labels)
        ),
    )


class ListAttrsTests(unittest.TestCase):
    def test_explicit_start_is_preserved(self):
        self.assertEqual(
            {"ordered": True, "start": 3}, list_attrs("ol", _ol('<ol start="3"><li>c</li></ol>'))
        )

    def test_default_and_invalid_start_are_omitted(self):
        self.assertEqual({"ordered": True}, list_attrs("ol", _ol("<ol><li>a</li></ol>")))
        self.assertEqual(
            {"ordered": True}, list_attrs("ol", _ol('<ol start="1"><li>a</li></ol>'))
        )
        self.assertEqual(
            {"ordered": True}, list_attrs("ol", _ol('<ol start="x"><li>a</li></ol>'))
        )

    def test_unordered_list_never_carries_start(self):
        self.assertEqual({"ordered": False}, list_attrs("ul", _ol("<ol><li>a</li></ol>")))


class MergeAdjacentOrderedListTests(unittest.TestCase):
    def test_contiguous_single_item_lists_become_one_list(self):
        merged = merge_adjacent_ordered_lists(
            [_list("b1", None, ["one"]), _list("b2", 2, ["two"]), _list("b3", 3, ["three"])]
        )
        self.assertEqual(1, len(merged))
        self.assertEqual(["one", "two", "three"], [c.inlines[0].text for c in merged[0].children])

    def test_multi_item_run_uses_item_count_for_continuity(self):
        merged = merge_adjacent_ordered_lists(
            [_list("b1", None, ["one", "two"]), _list("b2", 3, ["three"])]
        )
        self.assertEqual(1, len(merged))
        self.assertEqual(3, len(merged[0].children))

    def test_restarted_or_gapped_lists_stay_separate(self):
        self.assertEqual(2, len(merge_adjacent_ordered_lists([_list("b1", None, ["a"]), _list("b2", None, ["a"])])))
        self.assertEqual(2, len(merge_adjacent_ordered_lists([_list("b1", None, ["a"]), _list("b2", 7, ["g"])])))

    def test_unordered_and_non_list_blocks_are_untouched(self):
        paragraph = Block("p1", "paragraph", (InlineNode("text", text="gap"),))
        blocks = [_list("b1", None, ["a"]), paragraph, _list("b2", 2, ["b"])]
        self.assertEqual(3, len(merge_adjacent_ordered_lists(blocks)))


class OrderedListRenderTests(unittest.TestCase):
    def _render(self, blocks):
        document = CanonicalDocument(
            document_id="test:ordered",
            source={"canonical_url": "https://example.com/x", "site": "test"},
            revision={"source_hash": "sha256:0", "fetched_at": "2026-01-01T00:00:00+00:00"},
            title="Ordered",
            title_en="Ordered",
            blocks=tuple(blocks),
        )
        return render_source_markdown(CanonicalPackage(Path("."), document, {}))

    def test_merged_list_is_numbered_sequentially(self):
        rendered = self._render(merge_adjacent_ordered_lists(
            [_list("b1", None, ["one"]), _list("b2", 2, ["two"])]
        ))
        self.assertIn("1. one", rendered)
        self.assertIn("2. two", rendered)

    def test_unmergeable_list_still_renders_its_start(self):
        paragraph = Block("p1", "paragraph", (InlineNode("text", text="gap"),))
        rendered = self._render([_list("b1", None, ["one"]), paragraph, _list("b2", 2, ["two"])])
        self.assertIn("1. one", rendered)
        self.assertIn("2. two", rendered)


class QuotedOriginalListTests(unittest.TestCase):
    def test_ordered_original_keeps_numbers_and_escapes_the_dot(self):
        quoted = _render_original_list(_list("b1", None, ["one", "two"]), 2)
        self.assertEqual("> 1\\. one\n> 2\\. two", quoted)

    def test_ordered_original_honours_start(self):
        quoted = _render_original_list(_list("b1", 4, ["four"]), 2)
        self.assertEqual("> 4\\. four", quoted)

    def test_unordered_original_still_uses_bullets(self):
        block = Block(
            "b1",
            "list",
            attrs={"ordered": False},
            children=(Block("b1i0", "list_item", (InlineNode("text", text="a"),)),),
        )
        self.assertEqual("> • a", _render_original_list(block, 2))


if __name__ == "__main__":
    unittest.main()
