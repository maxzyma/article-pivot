from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from article_pivot.adapters.archive import TrendingDigestArchiveAdapter
from article_pivot.adapters.archive import DatedNotesArchiveAdapter
from article_pivot.package import CanonicalPackage
from article_pivot.renderers import render_bilingual_markdown
from article_pivot.publication import build_publication_document, publication_document_title
from article_pivot.validation import validate_document


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "harness"


class PivotRegressionTests(unittest.TestCase):
    def setUp(self):
        self.package = CanonicalPackage.load(FIXTURE)

    def test_fixture_is_valid(self):
        report = validate_document(self.package.document, self.package.translation("zh-CN"))
        self.assertTrue(report.ok, report.issues)

    def test_render_preserves_formula_code_and_heading_hierarchy(self):
        rendered = render_bilingual_markdown(self.package)
        self.assertIn("## 核心要点", rendered)
        self.assertIn("## 正文", rendered)
        self.assertIn("### 上下文工程", rendered)
        self.assertIn("> Context Engineering", rendered)
        self.assertNotIn("> ## Context Engineering", rendered)
        self.assertNotIn("\n# 上下文工程", rendered)
        self.assertIn("$s \\in \\mathcal{S}$", rendered)
        self.assertIn("```bibtex\n@article{weng2026harness", rendered)
        self.assertNotIn("| @article", rendered)
        self.assertIn("- 记忆与上下文退化。", rendered)
        self.assertIn("> • Memory and context degradation.", rendered)
        self.assertNotIn("> - Memory and context degradation.", rendered)
        self.assertIn("## 术语对照", rendered)
        self.assertIn("| Harness | 外层运行框架 |", rendered)

    def test_publication_document_owns_shared_title_and_metadata(self):
        publication = build_publication_document(self.package)
        self.assertEqual("bilingual-zh-first.v1", publication.profile)
        self.assertEqual("2026-07-04 面向自我改进的 Harness 工程", publication_document_title(publication))
        rendered = render_bilingual_markdown(self.package)
        self.assertIn("> 来源：Lil'Log / Lilian Weng，2026-07-04", rendered)
        self.assertIn("> 原文链接：https://lilianweng.github.io/posts/2026-07-04-harness/", rendered)
        self.assertIn("> 分类：AI Agent / Harness Engineering", rendered)

    def test_archive_plan_quotes_frontmatter_and_dry_run_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "sources").mkdir()
            (repo / "README.md").write_text("# Trending Diggest\n")
            adapter = TrendingDigestArchiveAdapter(repo)
            plan = adapter.plan(self.package, "lilian-weng")
            self.assertIn('title_zh: "面向自我改进的 Harness 工程"', plan.content)
            self.assertIn("## 核心要点", plan.content)
            self.assertIn("## 正文", plan.content)
            self.assertIn("## 术语对照", plan.content)
            self.assertFalse(plan.post_path.exists())
            self.assertFalse(plan.manifest_path.exists())
            self.assertFalse(plan.index_path.exists())

    def test_dated_archive_preserves_publication_overlays(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp)
            (archive / "article-index.md").write_text("# 文章索引\n")
            adapter = DatedNotesArchiveAdapter(archive)
            plan = adapter.plan(self.package)
            adapter.write(plan, self.package)
            self.assertTrue(plan.translation_path.is_file())
            self.assertTrue(plan.editorial_path.is_file())
            self.assertEqual(
                "bilingual-zh-first.v1",
                json.loads(plan.editorial_path.read_text())["profile"],
            )
            metadata = json.loads(plan.metadata_path.read_text())
            self.assertEqual("面向自我改进的 Harness 工程", metadata["title_zh"])
            self.assertEqual("Harness Engineering for Self-Improvement", metadata["title_en"])
            self.assertIn("[面向自我改进的 Harness 工程]", plan.index_content)
            self.assertIn("## 核心要点", plan.bilingual_path.read_text())

    def test_archive_write_is_idempotent_by_document_id(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "sources").mkdir()
            (repo / "README.md").write_text("# Trending Diggest\n")
            adapter = TrendingDigestArchiveAdapter(repo)
            plan = adapter.plan(self.package, "lilian-weng")
            first = adapter.write(plan)
            second = adapter.write(plan)
            adapter.verify(second)
            manifest = json.loads(first.manifest_path.read_text())
            self.assertEqual(1, len(manifest["documents"]))
            index = first.index_path.read_text()
            self.assertEqual(1, index.count(self.package.document.source["canonical_url"]))
            self.assertIn("[Markdown](posts/2026/07/", index)

    def test_archive_rejects_path_traversal_source_key(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "sources").mkdir()
            (repo / "README.md").write_text("# Trending Diggest\n")
            adapter = TrendingDigestArchiveAdapter(repo)
            with self.assertRaisesRegex(ValueError, "source_key"):
                adapter.plan(self.package, "../../private")

    def test_archive_rejects_slug_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "sources").mkdir()
            (repo / "README.md").write_text("# Trending Diggest\n")
            adapter = TrendingDigestArchiveAdapter(repo)
            plan = adapter.plan(self.package, "lilian-weng")
            plan.post_path.parent.mkdir(parents=True)
            plan.post_path.write_text('---\ndocument_id: "other:document"\n---\n')
            with self.assertRaisesRegex(ValueError, "collision"):
                adapter.plan(self.package, "lilian-weng")


if __name__ == "__main__":
    unittest.main()
