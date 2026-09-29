from __future__ import annotations

import json
import unittest

from article_pivot.adapters.source import ManusBlogAdapter, ManusBlogDiscovery
from article_pivot.adapters.source.lilian_weng import RawSnapshot


def rsc_page(record: dict, markdown: str) -> str:
    """Build a page shaped like manus.im: RSC rows streamed through __next_f."""
    body = markdown.encode("utf-8")
    payload = (
        f'0:{{"blog":{json.dumps(record, separators=(",", ":"))}}}'
        f'1a:{{"@context":"https://schema.org"}}'
        f"6d:T{len(body):x},{markdown}"
    )
    chunk = json.dumps(payload)[1:-1]
    return f'<html><body><script>self.__next_f.push([1,"{chunk}"])</script></body></html>'


RECORD = {
    "$typeName": "operation.v1.HomePageBlogI18n",
    "title": "Context Engineering for AI Agents",
    "desc": "Lessons from building Manus.",
    "recordUid": "context-engineering",
    "kindName": "Product",
    "createdAt": {"$typeName": "google.protobuf.Timestamp", "seconds": "$n1752852498"},
}

MARKDOWN = """*2025/7/18    -*-*Yichao 'Peak' Ji*

At the very beginning of the project we had to decide how to build the agent, and this intro paragraph is long enough to count as a real body for the length guard.

### Design Around the KV-Cache

Keeping the prompt prefix stable matters more than any other single practice when agents run long loops of tool calls in production.

1. Open settings.

   ![Enable SEO](https://cdn.example/seo.webp)

2. Check the dashboard.

[![Linked shot](https://cdn.example/linked.webp)](https://example.com/full)

![type=manus_video](https://cdn.example/demo.mov)

##

| Plan | Price |
| --- | --- |
| Pro | 20 |
"""


class ManusDiscoveryTests(unittest.TestCase):
    PAGE = """
    <a href="/zh-cn/blog/introducing-manus-2-0">
      <span>Product</span><span>·</span><span>September 28, 2026</span>
      <h3>Introducing Manus 2.0</h3><p>Manus 2.0 is here.</p>
    </a>
    <a href="/blog/introducing-manus-2-0"><span>Introducing Manus 2.0</span></a>
    <a href="/blog/year-one">
      <span>The First Annual Letter</span><span>Product</span><span>·</span><span>March 12, 2026</span>
    </a>
    <a href="/blog/old-post"><span>Old</span><span>Other</span><span>·</span><span>July 18, 2025</span></a>
    <a href="/blog/product">Product</a>
    """

    def test_cards_yield_titles_dates_and_canonical_urls_newest_first(self):
        items = ManusBlogDiscovery().discover(self.PAGE, known_urls={"https://manus.im/blog/old-post"})
        self.assertEqual(
            [
                ("Introducing Manus 2.0", "https://manus.im/blog/introducing-manus-2-0", "2026-09-28"),
                ("The First Annual Letter", "https://manus.im/blog/year-one", "2026-03-12"),
            ],
            [(item.title, item.url, item.published_at[:10]) for item in items],
        )


class ManusAdapterTests(unittest.TestCase):
    def parse(self, markdown: str = MARKDOWN, record: dict = RECORD):
        adapter = ManusBlogAdapter()
        snapshot = RawSnapshot(
            url="https://manus.im/blog/Context-Engineering",
            fetched_at="2026-09-29T00:00:00+00:00",
            html=rsc_page(record, markdown),
            source_hash="sha256:test",
        )
        document = adapter.parse(snapshot)
        return adapter, document

    def test_record_supplies_title_category_and_date(self):
        _, document = self.parse()
        self.assertEqual("manus-blog:context-engineering", document.document_id)
        self.assertEqual("Context Engineering for AI Agents", document.title)
        self.assertEqual(["Product"], document.metadata["categories"])
        self.assertEqual("2025-07-18T00:00:00+00:00", document.source["published_at"])

    def test_body_keeps_every_structure_and_drops_the_byline(self):
        adapter, document = self.parse()
        blocks = [block for root in document.blocks for block in root.walk()]
        images = [block.attrs["url"] for block in blocks if block.type == "image"]
        self.assertEqual(["https://cdn.example/seo.webp", "https://cdn.example/linked.webp"], images)
        self.assertEqual(1, sum(block.type == "table" for block in blocks))
        self.assertEqual(1, sum(block.type == "heading" for block in blocks))
        self.assertNotIn("Yichao", json.dumps(document.to_dict()))
        video = [
            node.attrs["url"]
            for block in blocks
            for node in block.inlines
            if node.type == "link"
        ]
        self.assertIn("https://cdn.example/demo.mov", video)
        self.assertTrue(adapter.validate(document).ok, adapter.validate(document).issues)

    def test_structure_the_block_parser_drops_fails_validation(self):
        adapter, document = self.parse(MARKDOWN + "\n##### Deep heading\n")
        report = adapter.validate(document)
        self.assertFalse(report.ok)
        self.assertIn("heading: expected 2, parsed 1", [issue.message for issue in report.issues])

    def test_source_markdown_names_the_archive_source(self):
        from pathlib import Path

        from article_pivot.package import CanonicalPackage
        from article_pivot.renderers import render_source_markdown

        _, document = self.parse()
        rendered = render_source_markdown(
            CanonicalPackage(Path("."), document, {}), source_label="Manus Blog / Manus"
        )
        self.assertIn("> 来源：Manus Blog / Manus，2025-07-18", rendered)
        self.assertNotIn("Lil'Log", rendered)

    def test_page_without_its_own_record_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "expected one blog record"):
            self.parse(record={"title": "not a blog record"})


if __name__ == "__main__":
    unittest.main()
