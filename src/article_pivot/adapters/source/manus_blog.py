"""Manus Blog source: listing discovery and Markdown-backed article parsing.

manus.im is a Next.js app. Article pages stream their Markdown source as a
React Server Component text row (``<id>:T<hex byte length>,<markdown>``) and
embed one ``HomePageBlogI18n`` record carrying title, category and creation
time. The Markdown is rendered to HTML and cut into blocks by the Claude Blog
block parser so every listing-style source shares one block model.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from markdown_it import MarkdownIt

from ...model import Block, CanonicalDocument
from ...validation import ValidationIssue, ValidationReport, validate_document
from .claude_blog import ClaudeBlogAdapter, _fetch_text, _plain_text, _SeqIdFactory
from .lilian_weng import DiscoveryItem, RawSnapshot
from .lists import merge_adjacent_ordered_lists


BLOG_URL = "https://manus.im/blog"
ALLOWED_HOSTS = {"manus.im", "www.manus.im"}
PARSER_VERSION = "manus-blog.v1"
RECORD_TYPE = '{"$typeName":"operation.v1.HomePageBlogI18n"'
LISTING_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+20\d{2}"
)
PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)
# Rows are concatenated without separators, so a row id may follow "}" or "]" directly.
TEXT_ROW_RE = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{1,6}:T([0-9a-f]+),")
# Leading "*2025/7/18 - * - *Author*" byline some posts carry inside the Markdown.
BYLINE_RE = re.compile(r"^\*(\d{4})/(\d{1,2})/(\d{1,2})[^\n]*\n+")
VIDEO_ALT = "type=manus_video"


def _slug_from_url(url: str) -> str:
    return urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]


def _canonical_url(href: str) -> str:
    path = urlparse(urljoin(BLOG_URL, href)).path
    # Localised listings (/zh-cn/blog/...) point at the same English original.
    path = re.sub(r"^/[a-z]{2}(?:-[a-z]{2})?/blog/", "/blog/", path)
    return urljoin(BLOG_URL, path)


def rsc_payload(page_html: str) -> str:
    """Concatenate the streamed RSC chunks back into one decoded string."""
    return "".join(json.loads(f'"{chunk}"') for chunk in PUSH_RE.findall(page_html))


def blog_records(payload: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    records = []
    start = payload.find(RECORD_TYPE)
    while start >= 0:
        try:
            record, _ = decoder.raw_decode(payload, start)
            records.append(record)
        except json.JSONDecodeError:
            pass
        start = payload.find(RECORD_TYPE, start + 1)
    return records


def article_markdown(payload: str) -> str:
    """Return the longest non-JSON RSC text row, which holds the post body."""
    encoded = payload.encode("utf-8")
    best = ""
    for match in TEXT_ROW_RE.finditer(payload):
        start = len(payload[: match.end()].encode("utf-8"))
        text = encoded[start : start + int(match.group(1), 16)].decode("utf-8", errors="replace")
        if text.lstrip()[:1] in {"{", "["}:
            continue
        if len(text) > len(best):
            best = text
    return best


def _timestamp_date(value: Any) -> str:
    seconds = str((value or {}).get("seconds", "")).removeprefix("$n")
    if not seconds.isdigit():
        return ""
    return datetime.fromtimestamp(int(seconds), timezone.utc).date().isoformat()


class ManusBlogDiscovery:
    def fetch(self, url: str = BLOG_URL) -> str:
        return _fetch_text(url)

    def discover(self, page_html: str, known_urls: Iterable[str] = ()) -> tuple[DiscoveryItem, ...]:
        """Cards read "<title> <category> · <date>" or "<category> · <date> <title> <desc>"."""
        known = set(known_urls)
        soup = BeautifulSoup(page_html, "html.parser")
        items: dict[str, DiscoveryItem] = {}
        for anchor in soup.select('a[href*="/blog/"]'):
            url = _canonical_url(anchor.get("href") or "")
            parts = [part for part in anchor.get_text("\n", strip=True).split("\n") if part]
            date_match = LISTING_DATE_RE.search(" ".join(parts))
            if url in known or url in items or not parts or not date_match:
                continue
            date = date_match.group(0)
            category = parts[parts.index("·") - 1] if "·" in parts[1:] else ""
            title = next((part for part in parts if part not in {category, "·", date}), "")
            if not title:
                continue
            published = datetime.strptime(date, "%B %d, %Y").date().isoformat()
            items[url] = DiscoveryItem(title=title, url=url, published_at=published + "T00:00:00+00:00")
        return tuple(sorted(items.values(), key=lambda item: item.published_at, reverse=True))


class ManusBlogAdapter:
    def __init__(self) -> None:
        self._blocks = ClaudeBlogAdapter()
        self._markdown = MarkdownIt("commonmark").enable("table")

    def match(self, url: str) -> bool:
        parsed = urlparse(url)
        slug = parsed.path.removeprefix("/blog/")
        return (
            parsed.scheme == "https"
            and parsed.netloc in ALLOWED_HOSTS
            and parsed.path.startswith("/blog/")
            and bool(slug)
            and "/" not in slug
        )

    def fetch(self, url: str) -> RawSnapshot:
        if not self.match(url):
            raise ValueError(f"unsupported Manus Blog URL: {url}")
        html = _fetch_text(url)
        return RawSnapshot(
            url=url,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            html=html,
            source_hash="sha256:" + hashlib.sha256(html.encode()).hexdigest(),
        )

    def parse(self, snapshot: RawSnapshot) -> CanonicalDocument:
        payload = rsc_payload(snapshot.html)
        records = blog_records(payload)
        if len(records) != 1:
            raise ValueError(f"expected one blog record, found {len(records)}: {snapshot.url}")
        record = records[0]
        markdown = article_markdown(payload)
        byline = BYLINE_RE.match(markdown)
        if byline:
            markdown = markdown[byline.end() :]
        published = _timestamp_date(record.get("createdAt"))
        if not published and byline:
            published = "{:04d}-{:02d}-{:02d}".format(*map(int, byline.groups()))

        blocks = self._parse_markdown(markdown, snapshot.url)
        expected = self._markdown_counts(markdown)
        if sum(len(_plain_text(b.inlines)) for b in blocks if b.inlines) < 200:
            raise ValueError(f"article body too short: {snapshot.url}")

        title = str(record.get("title", "")).strip()
        slug = _slug_from_url(snapshot.url)
        all_blocks = [b for root in blocks for b in root.walk()]
        return CanonicalDocument(
            document_id=f"manus-blog:{slug.lower()}",
            source={
                "canonical_url": snapshot.url,
                "site": "manus-blog",
                "author": "Manus",
                "published_at": published + "T00:00:00+00:00" if published else "",
                "source_timezone": "UTC",
            },
            revision={
                "source_hash": snapshot.source_hash,
                "fetched_at": snapshot.fetched_at,
                "parser_version": PARSER_VERSION,
            },
            title=title,
            title_en=title,
            blocks=tuple(blocks),
            metadata={
                "slug": slug.lower(),
                "source_slug": slug,
                "source_profile": PARSER_VERSION,
                "source_counts": expected,
                "categories": [record["kindName"]] if record.get("kindName") else [],
                "summary_hint": str(record.get("desc", "")).strip(),
            },
            assets=tuple(
                {"type": "image", "url": b.attrs["url"], "alt": b.attrs.get("alt", "")}
                for b in all_blocks
                if b.type == "image"
            ),
        )

    def validate(self, document: CanonicalDocument) -> ValidationReport:
        report = validate_document(document)
        actual = Counter(block.type for root in document.blocks for block in root.walk())
        issues = list(report.issues)
        for block_type, expected in document.metadata.get("source_counts", {}).items():
            if actual[block_type] != expected:
                issues.append(
                    ValidationIssue(
                        "source.count_mismatch",
                        f"{block_type}: expected {expected}, parsed {actual[block_type]}",
                    )
                )
        return ValidationReport(tuple(issues))

    def _markdown_counts(self, markdown: str) -> dict[str, int]:
        """Count structures from Markdown tokens, independent of the block parser."""
        tokens = self._markdown.parse(markdown)
        inline = [child for token in tokens for child in token.children or ()]
        return {
            "heading": sum(
                1
                for token, inline in zip(tokens, tokens[1:])
                if token.type == "heading_open" and inline.content.strip()
            ),
            "image": sum(
                1 for child in inline if child.type == "image" and child.content != VIDEO_ALT
            ),
            "table": sum(1 for token in tokens if token.type == "table_open"),
            "code": sum(1 for token in tokens if token.type in {"fence", "code_block"}),
        }

    def _parse_markdown(self, markdown: str, base_url: str) -> list[Block]:
        soup = BeautifulSoup(self._markdown.render(markdown), "html.parser")
        for image in soup.find_all("img"):
            # A linked image ([![alt](src)](href)) is still a figure, not link text.
            if image.parent.name == "a" and not image.parent.get_text(strip=True):
                image.parent.replace_with(image)
            # Manus embeds videos as images with a marker alt; keep them as links.
            if image.get("alt") == VIDEO_ALT:
                link = soup.new_tag("a", href=image.get("src", ""))
                link.string = "Video"
                image.replace_with(link)
        factory = _SeqIdFactory()
        blocks: list[Block] = []
        for child in soup.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "h1":
                child.name = "h2"
            parsed = self._blocks._parse_block(child, base_url, factory)
            if parsed is not None:
                blocks.extend(parsed if isinstance(parsed, list) else [parsed])
        return list(merge_adjacent_ordered_lists(blocks))
