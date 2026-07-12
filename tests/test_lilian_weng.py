from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from article_pivot.adapters.archive import DatedNotesArchiveAdapter
from article_pivot.adapters.source.lilian_weng import LilianWengAdapter, LilianWengDiscovery, RawSnapshot
from article_pivot.package import CanonicalPackage
from article_pivot.renderers import render_source_markdown


FIXTURES = Path(__file__).parent / "fixtures"


class LilianWengAdapterTests(unittest.TestCase):
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
        self.assertEqual(["heading", "heading"], [block.type for block in document.blocks if block.type == "heading"])
        self.assertEqual(1, len(document.assets))
        block_types = [block.type for block in document.blocks]
        self.assertIn("table", block_types)
        self.assertIn("code", block_types)
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
            self.assertIn("| Group | Tools |", markdown)
            self.assertIn("```bibtex", markdown)

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

            adapter = DatedNotesArchiveAdapter(archive)
            plan = adapter.plan(package)
            plan.article_dir.mkdir(parents=True)
            with self.assertRaises(FileExistsError):
                adapter.write(plan, package)


if __name__ == "__main__":
    unittest.main()
