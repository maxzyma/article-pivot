from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from article_pivot.adapters.archive import DatedNotesArchiveAdapter
from article_pivot.adapters.source.lilian_weng import (
    LilianWengAdapter,
    LilianWengDiscovery,
    RawSnapshot,
    _text_nodes,
)
from article_pivot.model import TranslationOverlay, TranslationSegment
from article_pivot.package import CanonicalPackage
from article_pivot.renderers import render_bilingual_markdown, render_source_markdown


FIXTURES = Path(__file__).parent / "fixtures"


class LilianWengAdapterTests(unittest.TestCase):
    def test_math_tokenizer_does_not_pair_display_delimiters_with_inline_math(self):
        nodes = _text_nodes("$$ x = 1 $$ where $y$ denotes one value")
        self.assertEqual(
            ["text", "inline_math", "text", "text", "inline_math", "text"],
            [node.type for node in nodes],
        )
        self.assertEqual([" x = 1 ", "y"], [node.text for node in nodes if node.type == "inline_math"])
        self.assertIn(" where ", "".join(node.text for node in nodes if node.type == "text"))

    def test_discovery_filters_known_urls_and_sorts_newest_first(self):
        xml = (FIXTURES / "lilian-feed.xml").read_text()
        known = {"https://lilianweng.github.io/posts/2026-06-24-scaling-laws/"}
        items = LilianWengDiscovery().discover(xml, known)
        self.assertEqual(1, len(items))
        self.assertEqual("Harness Engineering for Self-Improvement", items[0].title)

    def test_source_adapter_builds_canonical_structure_without_toc(self):
        html = (FIXTURES / "lilian-harness.html").read_text()
        snapshot = RawSnapshot(
            url="https://lilianweng.github.io/posts/2026-07-04-harness/",
            fetched_at="2026-07-12T00:00:00+00:00",
            html=html,
            source_hash="sha256:" + hashlib.sha256(html.encode()).hexdigest(),
        )
        adapter = LilianWengAdapter()
        document = adapter.parse(snapshot)
        self.assertTrue(adapter.validate(document).ok)
        self.assertEqual("lilian-weng:2026-07-04-harness", document.document_id)
        self.assertEqual("harness-engineering-for-self-improvement", document.metadata["slug"])
        self.assertEqual("lilian-weng.v5", document.metadata["source_profile"])
        self.assertEqual(3, document.metadata["source_counts"]["math"])
        self.assertEqual(3, document.metadata["source_counts"]["code"])
        self.assertEqual(
            ["heading", "heading", "heading"],
            [block.type for block in document.blocks if block.type == "heading"],
        )
        self.assertEqual(2, len(document.assets))
        block_types = [block.type for block in document.blocks]
        self.assertIn("table", block_types)
        self.assertIn("code", block_types)
        self.assertIn("math", block_types)
        self.assertEqual(3, block_types.count("math"))
        self.assertNotIn(
            "nested_list_formula",
            str(next(block for block in document.blocks if block.type == "list").to_dict()),
        )
        self.assertIn("Inner step.", str(next(block for block in document.blocks if block.type == "list").to_dict()))
        self.assertIn("This paragraph must not be dropped.", str(document.to_dict()))
        heading = next(block for block in document.blocks if block.type == "heading")
        self.assertNotIn("#", str(heading.to_dict()))
        self.assertNotIn("Table of Contents", " ".join(str(block.to_dict()) for block in document.blocks))

    def test_source_markdown_preserves_formula_table_and_code(self):
        html = (FIXTURES / "lilian-harness.html").read_text()
        snapshot = RawSnapshot(
            url="https://lilianweng.github.io/posts/2026-07-04-harness/",
            fetched_at="2026-07-12T00:00:00+00:00",
            html=html,
            source_hash="sha256:" + hashlib.sha256(html.encode()).hexdigest(),
        )
        document = LilianWengAdapter().parse(snapshot)
        with tempfile.TemporaryDirectory() as temp:
            package = CanonicalPackage.write(temp, document, raw_html=html)
            markdown = render_source_markdown(package)
            self.assertIn("$s \\in \\mathcal{S}$", markdown)
            self.assertIn("$k_{\\sigma}$", markdown)
            self.assertIn("$$\nc_s=(\\rho_s,F_s)\n$$", markdown)
            self.assertIn("| Group | Tools |", markdown)
            self.assertIn("```bibtex", markdown)
            self.assertNotIn("[](", markdown)

    def test_source_count_mismatch_fails_validation(self):
        html = (FIXTURES / "lilian-harness.html").read_text()
        snapshot = RawSnapshot(
            url="https://lilianweng.github.io/posts/2026-07-04-harness/",
            fetched_at="2026-07-12T00:00:00+00:00",
            html=html,
            source_hash="sha256:" + hashlib.sha256(html.encode()).hexdigest(),
        )
        adapter = LilianWengAdapter()
        document = adapter.parse(snapshot)
        metadata = dict(document.metadata)
        metadata["source_counts"] = dict(metadata["source_counts"], math=4)
        report = adapter.validate(replace(document, metadata=metadata))
        self.assertFalse(report.ok)
        self.assertIn("source.count_mismatch", [issue.code for issue in report.issues])

    def test_bilingual_renderer_uses_translated_table_attrs(self):
        html = (FIXTURES / "lilian-harness.html").read_text()
        snapshot = RawSnapshot(
            url="https://lilianweng.github.io/posts/2026-07-04-harness/",
            fetched_at="2026-07-12T00:00:00+00:00",
            html=html,
            source_hash="sha256:" + hashlib.sha256(html.encode()).hexdigest(),
        )
        document = LilianWengAdapter().parse(snapshot)
        segments = {}
        for block in document.all_blocks():
            if block.type in {"heading", "paragraph", "list_item"}:
                segments[block.id] = TranslationSegment(block.id, block.inlines)
            elif block.type == "table":
                segments[block.id] = TranslationSegment(
                    block.id,
                    (),
                    attrs={"headers": ["分组", "工具"], "rows": [["输入输出", "读取、写入"]]},
                )
        overlay = TranslationOverlay(
            locale="zh-CN",
            source_revision=document.revision["source_hash"],
            title="面向自我改进的 Harness 工程",
            segments=segments,
        )
        with tempfile.TemporaryDirectory() as temp:
            package = CanonicalPackage(Path(temp), document, {"zh-CN": overlay})
            markdown = render_bilingual_markdown(package)
            self.assertIn("| 分组 | 工具 |", markdown)
            self.assertIn("> **Group：** IO", markdown)
            self.assertIn("> **Tools：** read, write", markdown)
            self.assertNotIn("> | Group | Tools |", markdown)

    def test_notes_archive_dry_plan_uses_published_date(self):
        html = (FIXTURES / "lilian-harness.html").read_text()
        snapshot = RawSnapshot(
            url="https://lilianweng.github.io/posts/2026-07-04-harness/",
            fetched_at="2026-07-12T00:00:00+00:00",
            html=html,
            source_hash="sha256:" + hashlib.sha256(html.encode()).hexdigest(),
        )
        document = LilianWengAdapter().parse(snapshot)
        with tempfile.TemporaryDirectory() as package_temp, tempfile.TemporaryDirectory() as archive_temp:
            archive = Path(archive_temp)
            (archive / "article-index.md").write_text("# 文章索引\n")
            package = CanonicalPackage.write(package_temp, document, raw_html=html)
            plan = DatedNotesArchiveAdapter(archive).plan(package)
            self.assertIn("2026-07/2026-07-04/harness-engineering-for-self-improvement", str(plan.article_dir))
            self.assertFalse(plan.article_dir.exists())
            self.assertIn("harness-engineering-for-self-improvement.md", plan.index_content)
            self.assertIsNone(plan.editorial_path)

    def test_translation_overlay_starts_pending_and_archive_refuses_overwrite(self):
        html = (FIXTURES / "lilian-harness.html").read_text()
        snapshot = RawSnapshot(
            url="https://lilianweng.github.io/posts/2026-07-04-harness/",
            fetched_at="2026-07-12T00:00:00+00:00",
            html=html,
            source_hash="sha256:" + hashlib.sha256(html.encode()).hexdigest(),
        )
        document = LilianWengAdapter().parse(snapshot)
        with tempfile.TemporaryDirectory() as package_temp, tempfile.TemporaryDirectory() as archive_temp:
            archive = Path(archive_temp)
            (archive / "article-index.md").write_text("# 文章索引\n")
            package = CanonicalPackage.write(package_temp, document, raw_html=html)
            overlay_path = package.initialize_translation("zh-CN")
            overlay = CanonicalPackage.load(package_temp).translation("zh-CN")
            self.assertTrue(overlay_path.is_file())
            self.assertTrue(overlay.segments)
            self.assertTrue(all(segment.status == "pending" for segment in overlay.segments.values()))
            table_id = next(block.id for block in document.blocks if block.type == "table")
            self.assertIn(table_id, overlay.segments)

            adapter = DatedNotesArchiveAdapter(archive)
            plan = adapter.plan(package)
            plan.article_dir.mkdir(parents=True)
            with self.assertRaises(FileExistsError):
                adapter.write(plan, package)


if __name__ == "__main__":
    unittest.main()
