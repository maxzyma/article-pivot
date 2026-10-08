from __future__ import annotations

import unittest

from article_pivot.adapters.source import ClaudeBlogAdapter, ClaudeBlogDiscovery
from article_pivot.adapters.source.lilian_weng import RawSnapshot


LISTING = """
<div class="grid">
  <div class="card">
    <a href="/blog/claude-mythos-security" data-cta-copy="How teams use Claude Mythos to secure code">
      Read more</a>
    <span>Enterprise AI</span><span>Oct 8, 2026</span>
  </div>
  <a href="https://claude.dev/blog/automating-eval-design/">
    <span>Article</span><span>Oct 7, 2026</span>
    <h3>Automating eval design and hillclimbing with Claude</h3>
    <p>Principles for designing evals.</p>
  </a>
  <a href="https://claude.dev/">claude.dev</a>
  <a href="https://example.com/blog/elsewhere">Elsewhere Oct 6, 2026</a>
</div>
"""

DEV_ARTICLE = """
<html><head><title>Automating eval design / claude.dev Blog</title>
<script type="application/ld+json">{"datePublished": "2026-09-28"}</script></head>
<body><h1>Automating eval design and hillclimbing with Claude</h1>
<div class="prose">
  <section><p>Evaluations provide a signal on how your app or skill is performing, and good ones
  make every later change measurable instead of a matter of taste or anecdote.</p></section>
  <section><h2 id="eval-design">EVAL DESIGN</h2>
    <p>Well designed evaluations have a few common elements that keep them honest over time,
    so that a higher score really means a better system for the people using it.</p>
    <ol><li><strong>Eval tasks mirror production.</strong> Sample real tasks.</li></ol>
    <figure><img src="/media/figure-1.png" alt="Figure 1"></figure>
    <pre><code class="language-bash">claude update</code></pre>
  </section>
</div></body></html>
"""


class ClaudeDiscoveryTests(unittest.TestCase):
    def test_cards_keep_their_own_title_and_only_blog_hosts(self):
        items = ClaudeBlogDiscovery().discover(LISTING)
        self.assertEqual(
            [
                ("How teams use Claude Mythos to secure code", "https://claude.com/blog/claude-mythos-security"),
                (
                    "Automating eval design and hillclimbing with Claude",
                    "https://claude.dev/blog/automating-eval-design/",
                ),
            ],
            [(item.title, item.url) for item in items],
        )


RESOURCES_LISTING = """
<a href="/resources/articles/claude-now-works-in-google-docs">
  <span>Article</span><span>Oct 6, 2026</span><h3>Claude now works with Google Docs</h3></a>
<a href="/resources/articles/already-archived-post">
  <span>Article</span><span>Sep 1, 2026</span><h3>Already archived</h3></a>
<a href="/resources/product-announcements">Announcements</a>
"""

RESOURCES_ARTICLE = """
<html><head><script type="application/ld+json">{"datePublished": "2026-10-06"}</script></head>
<body><h1>Claude now works with Google Docs</h1>
<ul class="meta">
  <li><div>Category</div><div><a href="/resources/product-announcements">Announcements</a></div></li>
  <li><div>Product</div><div>Claude Enterprise</div></li>
</ul>
<div class="w-richtext"><p>Teams that run on Google Workspace can now bring Claude into their documents,
spreadsheets and slides, and work on those files directly from a Claude conversation as well.</p>
<h2>How it works</h2><p>Install the add-on from the Workspace marketplace and connect your account.</p></div>
</body></html>
"""


class ClaudeResourcesTests(unittest.TestCase):
    def test_resources_listing_treats_old_blog_urls_as_known(self):
        items = ClaudeBlogDiscovery().discover(
            RESOURCES_LISTING, known_urls={"https://claude.com/blog/already-archived-post"}
        )
        self.assertEqual(
            [("Claude now works with Google Docs", "https://claude.com/resources/articles/claude-now-works-in-google-docs")],
            [(item.title, item.url) for item in items],
        )

    def test_resources_article_reads_the_new_category_field(self):
        adapter = ClaudeBlogAdapter()
        url = "https://claude.com/resources/articles/claude-now-works-in-google-docs"
        self.assertTrue(adapter.match(url))
        self.assertFalse(adapter.match("https://claude.com/resources/product-announcements"))
        document = adapter.parse(RawSnapshot(url, "t", RESOURCES_ARTICLE, "sha256:x"))
        self.assertEqual(["Announcements"], document.metadata["categories"])
        self.assertEqual("claude-blog:claude-now-works-in-google-docs", document.document_id)


class ClaudeDevArticleTests(unittest.TestCase):
    def test_developer_blog_article_parses_sections_and_absolute_images(self):
        adapter = ClaudeBlogAdapter()
        url = "https://claude.dev/blog/automating-eval-design/"
        self.assertTrue(adapter.match(url))
        self.assertFalse(adapter.match("https://claude.dev/"))
        document = adapter.parse(RawSnapshot(url, "2026-10-08T00:00:00+00:00", DEV_ARTICLE, "sha256:x"))
        blocks = [block for root in document.blocks for block in root.walk()]
        self.assertEqual(
            ["paragraph", "heading", "paragraph", "list", "list_item", "image", "code"],
            [block.type for block in blocks],
        )
        image = next(block for block in blocks if block.type == "image")
        self.assertEqual("https://claude.dev/media/figure-1.png", image.attrs["url"])
        self.assertEqual("claude-blog:automating-eval-design", document.document_id)
        self.assertEqual("2026-09-28T00:00:00+00:00", document.source["published_at"])
        self.assertTrue(adapter.validate(document).ok, adapter.validate(document).issues)


if __name__ == "__main__":
    unittest.main()
