from __future__ import annotations

import hashlib
import html as html_mod
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from ...model import Block, CanonicalDocument, InlineNode
from ...validation import ValidationIssue, ValidationReport, validate_document
from .lilian_weng import DiscoveryItem, RawSnapshot


BLOG_URL = "https://claude.com/blog"
ALLOWED_HOST = "claude.com"
DATE_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+20\d{2}",
    re.I,
)
KNOWN_CATEGORIES = [
    "Enterprise AI",
    "Claude Code",
    "Product announcements",
    "Agents",
    "Product",
    "Research",
    "Company",
]


def _slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", slug).strip("-").lower()


def _parse_human_date(value: str) -> str:
    value = value.replace(".", "")
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html_mod.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _ordered_categories_from_text(text: str, categories: list[str]) -> list[str]:
    positions = []
    for category in categories:
        index = text.find(category)
        if index >= 0:
            positions.append((index, -len(category), category))
    ordered: list[str] = []
    for _, _, category in sorted(positions):
        if any(existing.startswith(category) for existing in ordered):
            continue
        ordered.append(category)
    return ordered


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "article-pivot/0.1 (claude-blog)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == 3:
                break
            time.sleep(2 * attempt)
    raise RuntimeError(f"fetch failed after retries: {url}: {last_error}") from last_error


class _SeqIdFactory:
    def __init__(self):
        self._seq = 0

    def next(self) -> str:
        self._seq += 1
        return f"b{self._seq:03d}"


def _inline_nodes(element: Tag, base_url: str) -> tuple[InlineNode, ...]:
    nodes: list[InlineNode] = []
    for child in element.children:
        if isinstance(child, NavigableString):
            text = str(child)
            if text:
                nodes.append(InlineNode(type="text", text=text))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        if name == "br":
            nodes.append(InlineNode(type="line_break"))
            continue
        if name in {"ul", "ol", "pre", "blockquote", "table", "figure"}:
            continue
        if name == "a":
            href = (child.get("href") or "").strip()
            children = _inline_nodes(child, base_url)
            if href and href != "#":
                nodes.append(
                    InlineNode(
                        type="link",
                        attrs={"url": urljoin(base_url, href)},
                        children=children,
                        text=child.get_text(" ", strip=False) if not children else "",
                    )
                )
            else:
                nodes.extend(children or (InlineNode(type="text", text=child.get_text()),))
            continue
        if name in {"strong", "b"}:
            children = _inline_nodes(child, base_url)
            nodes.append(InlineNode(type="strong", children=children, text=child.get_text() if not children else ""))
            continue
        if name in {"em", "i"}:
            children = _inline_nodes(child, base_url)
            nodes.append(InlineNode(type="emphasis", children=children, text=child.get_text() if not children else ""))
            continue
        if name == "code":
            nodes.append(InlineNode(type="inline_code", text=child.get_text()))
            continue
        children = _inline_nodes(child, base_url)
        nodes.extend(children or (InlineNode(type="text", text=child.get_text()),))
    return tuple(nodes)


def _plain_text(inlines: tuple[InlineNode, ...]) -> str:
    def node_text(node: InlineNode) -> str:
        return "".join(node_text(c) for c in node.children) if node.children else node.text

    return "".join(node_text(n) for n in inlines)


class ClaudeBlogDiscovery:
    def fetch(self, url: str = BLOG_URL) -> str:
        return _fetch_text(url)

    def discover(
        self, page_html: str, known_urls: Iterable[str] = ()
    ) -> tuple[DiscoveryItem, ...]:
        known = set(known_urls)
        soup = BeautifulSoup(page_html, "html.parser")
        by_url: dict[str, dict] = {}

        for anchor in soup.select('a[href*="/blog/"]'):
            href = anchor.get("href") or ""
            url = urljoin(BLOG_URL, href)
            if "/blog/category/" in url:
                continue
            slug = _slug_from_url(url)
            if not slug or slug == "blog":
                continue
            if url in known:
                continue

            block = None
            parent = anchor
            for _ in range(10):
                parent = parent.parent
                if parent is None:
                    break
                text = parent.get_text(" ", strip=True)
                if DATE_RE.search(text):
                    block = parent
                    break
            if block is None:
                continue

            text = block.get_text(" ", strip=True)
            date_match = DATE_RE.search(text)
            if not date_match:
                continue
            date = _parse_human_date(date_match.group(0))
            if not date:
                continue

            has_cta_title = bool(anchor.get("data-cta-copy"))
            title = anchor.get("data-cta-copy") or ""
            heading = block.find(re.compile("^h[1-4]$"))
            if not title and heading:
                title = heading.get_text(" ", strip=True)
            if not title:
                after = text[date_match.end():].strip()
                title = re.sub(r"\bRead more\b.*$", "", after).strip()
            title = re.sub(r"\s+", " ", html_mod.unescape(title)).strip()
            if not title or title.lower() == "read more":
                title = slug.replace("-", " ").title()

            category_links = [
                _clean_text(a.get_text(" ", strip=True))
                for a in block.select('a[href*="/blog/category/"]')
                if _clean_text(a.get_text(" ", strip=True))
            ]
            categories_found = category_links or _ordered_categories_from_text(
                text, KNOWN_CATEGORIES
            )

            quality = 1 if has_cta_title else 0
            existing = by_url.get(url)
            if (
                not existing
                or quality > existing["_q"]
                or (
                    quality == existing["_q"]
                    and (
                        (categories_found and not existing["categories"])
                        or len(title) > len(existing["title"])
                    )
                )
            ):
                by_url[url] = {
                    "title": title,
                    "url": url,
                    "date": date,
                    "categories": categories_found,
                    "_q": quality,
                }

        items: list[DiscoveryItem] = []
        for entry in by_url.values():
            published_at = entry["date"] + "T00:00:00+00:00"
            items.append(
                DiscoveryItem(
                    title=entry["title"],
                    url=entry["url"],
                    published_at=published_at,
                )
            )
        return tuple(sorted(items, key=lambda x: x.published_at, reverse=True))


class ClaudeBlogAdapter:
    def match(self, url: str) -> bool:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.netloc == ALLOWED_HOST
            and parsed.path.startswith("/blog/")
            and parsed.path != "/blog/"
            and "/blog/category/" not in parsed.path
        )

    def fetch(self, url: str) -> RawSnapshot:
        if not self.match(url):
            raise ValueError(f"unsupported Claude Blog URL: {url}")
        html = _fetch_text(url)
        return RawSnapshot(
            url=url,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            html=html,
            source_hash="sha256:" + hashlib.sha256(html.encode()).hexdigest(),
        )

    def parse(self, snapshot: RawSnapshot) -> CanonicalDocument:
        soup = BeautifulSoup(snapshot.html, "html.parser")
        # claude.com serves React streaming SSR markup whose Suspense boundary
        # markers (<!--$-->, <!--/$-->, <!--$!-->) are HTML comments. They wrap
        # inline <br/> nodes, so BeautifulSoup's get_text would otherwise surface
        # their "$"/"/$" payload as literal text and corrupt the canonical body
        # (and get misread as LaTeX by downstream renderers). Strip them first.
        for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
            comment.extract()
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""

        body_nodes = [
            node
            for node in soup.select(".u-rich-text-blog")
            if len(node.get_text(" ", strip=True)) >= 50
        ]
        if not body_nodes:
            candidates = soup.select(".w-richtext")
            body = (
                max(candidates, key=lambda e: len(e.get_text(" ", strip=True)))
                if candidates
                else soup.find("main")
            )
            body_nodes = [body] if body is not None else []
        if not body_nodes:
            raise ValueError(f"article body not found: {snapshot.url}")

        factory = _SeqIdFactory()
        blocks: list[Block] = []
        seen_first_heading = False
        has_h2 = False
        intro_count = 0

        for node in body_nodes:
            for child in node.children:
                if not isinstance(child, Tag):
                    continue
                parsed = self._parse_block(child, snapshot.url, factory)
                if parsed is None:
                    continue
                parsed_blocks = parsed if isinstance(parsed, list) else [parsed]
                for block in parsed_blocks:
                    if block.type == "heading":
                        level = block.attrs.get("level", 2)
                        if level == 2:
                            has_h2 = True
                        seen_first_heading = True
                    elif not seen_first_heading and block.type in {
                        "paragraph",
                        "list",
                    }:
                        intro_count += 1
                    blocks.append(block)

        total_text = sum(
            len(_plain_text(b.inlines))
            for b in blocks
            if b.inlines
        )
        if not blocks or total_text < 200:
            raise ValueError(f"article body too short: {snapshot.url}")

        if not has_h2:
            intro_count = 0

        categories = self._extract_categories(soup)
        published_at = self._extract_published_at(soup, snapshot.html)
        source_slug = _slug_from_url(snapshot.url)

        all_blocks = [b for root in blocks for b in root.walk()]
        source_counts = {
            "heading": sum(1 for b in all_blocks if b.type == "heading"),
            "image": sum(1 for b in all_blocks if b.type == "image"),
            "table": sum(1 for b in all_blocks if b.type == "table"),
            "code": sum(1 for b in all_blocks if b.type == "code"),
        }

        assets = tuple(
            {"type": "image", "url": b.attrs["url"], "alt": b.attrs.get("alt", "")}
            for b in all_blocks
            if b.type == "image"
        )

        return CanonicalDocument(
            document_id=f"claude-blog:{source_slug}",
            source={
                "canonical_url": snapshot.url,
                "site": "claude-blog",
                "author": "Anthropic",
                "published_at": published_at,
                "source_timezone": "UTC",
            },
            revision={
                "source_hash": snapshot.source_hash,
                "fetched_at": snapshot.fetched_at,
                "parser_version": "claude-blog.v1",
            },
            title=title,
            title_en=title,
            blocks=tuple(blocks),
            metadata={
                "slug": source_slug,
                "source_slug": source_slug,
                "source_profile": "claude-blog.v1",
                "source_counts": source_counts,
                "categories": categories,
                "intro_paragraph_count": intro_count,
            },
            assets=assets,
        )

    def validate(self, document: CanonicalDocument) -> ValidationReport:
        report = validate_document(document)
        actual = Counter(
            block.type for root in document.blocks for block in root.walk()
        )
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

    def _parse_block(
        self, element: Tag, base_url: str, factory: _SeqIdFactory
    ) -> Block | list[Block] | None:
        name = element.name.lower()

        if name in {"h2", "h3", "h4"}:
            inlines = _inline_nodes(element, base_url)
            if not _plain_text(inlines).strip():
                return None
            return Block(factory.next(), "heading", inlines, {"level": int(name[1])})

        if name == "p":
            embedded = self._extract_embedded_blocks(element, base_url, factory)
            inlines = _inline_nodes(element, base_url)
            text = _plain_text(inlines).strip()
            result: list[Block] = []
            if text:
                result.append(Block(factory.next(), "paragraph", inlines))
            result.extend(embedded)
            return result if result else None

        if name in {"ul", "ol"}:
            items: list[Block] = []
            for li in element.find_all("li", recursive=False):
                inlines = _inline_nodes(li, base_url)
                nested_children: list[Block] = []
                for nested_list in li.find_all(["ul", "ol"], recursive=False):
                    nested_block = self._parse_block(nested_list, base_url, factory)
                    if isinstance(nested_block, list):
                        nested_children.extend(nested_block)
                    elif nested_block is not None:
                        nested_children.append(nested_block)
                items.append(
                    Block(factory.next(), "list_item", inlines, children=tuple(nested_children))
                )
            if not items:
                return None
            return Block(
                factory.next(), "list", attrs={"ordered": name == "ol"}, children=tuple(items)
            )

        if name == "blockquote":
            children: list[Block] = []
            for child in element.children:
                if not isinstance(child, Tag):
                    continue
                parsed = self._parse_block(child, base_url, factory)
                if isinstance(parsed, list):
                    children.extend(parsed)
                elif parsed is not None:
                    children.append(parsed)
            if not children:
                inlines = _inline_nodes(element, base_url)
                if _plain_text(inlines).strip():
                    children.append(Block(factory.next(), "paragraph", inlines))
            if not children:
                return None
            return Block(factory.next(), "blockquote", children=tuple(children))

        if name == "pre":
            code_node = element.find("code") or element
            text = code_node.get_text("", strip=False).strip("\n")
            if not text.strip():
                return None
            lang = ""
            for cls in code_node.get("class") or []:
                if str(cls).startswith("language-"):
                    lang = str(cls).removeprefix("language-")
                    break
            return Block(factory.next(), "code", attrs={"code": text, "language": lang})

        if name == "figure":
            img = element.find("img")
            if not img:
                return None
            src = img.get("src") or img.get("data-src") or ""
            if not src or "placeholder.svg" in src:
                return None
            alt = re.sub(r"\s+", " ", img.get("alt") or "").strip()
            caption = element.find("figcaption")
            if not alt and caption:
                alt = caption.get_text(" ", strip=True)
            return Block(factory.next(), "image", attrs={"url": src, "alt": alt})

        if name == "img":
            src = element.get("src") or element.get("data-src") or ""
            if not src or "placeholder.svg" in src:
                return None
            alt = re.sub(r"\s+", " ", element.get("alt") or "").strip()
            return Block(factory.next(), "image", attrs={"url": src, "alt": alt})

        if name == "table":
            rows = [
                [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                for row in element.find_all("tr")
            ]
            if not rows:
                return None
            headers = rows[0] if element.find("th") else []
            body_rows = rows[1:] if headers else rows
            return Block(factory.next(), "table", attrs={"headers": headers, "rows": body_rows})

        if name == "hr":
            return Block(factory.next(), "divider")

        if name == "div":
            results: list[Block] = []
            for child in element.children:
                if not isinstance(child, Tag):
                    continue
                parsed = self._parse_block(child, base_url, factory)
                if isinstance(parsed, list):
                    results.extend(parsed)
                elif parsed is not None:
                    results.append(parsed)
            return results if results else None

        return None

    def _extract_embedded_blocks(
        self, element: Tag, base_url: str, factory: _SeqIdFactory
    ) -> list[Block]:
        results: list[Block] = []
        for child in element.children:
            if not isinstance(child, Tag):
                continue
            if child.name.lower() in {"pre", "ul", "ol", "blockquote", "table", "figure", "img"}:
                parsed = self._parse_block(child, base_url, factory)
                if isinstance(parsed, list):
                    results.extend(parsed)
                elif parsed is not None:
                    results.append(parsed)
        return results

    def _extract_published_at(self, soup: BeautifulSoup, html: str) -> str:
        """Resolve the article publish date to an ISO 8601 UTC timestamp.

        Claude Blog article pages expose a JSON-LD ``datePublished`` (human or
        ISO shaped); fall back to the first human date in the visible text.
        """
        raw = ""
        match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
        if match:
            raw = match.group(1).strip()
        if not raw:
            date_match = DATE_RE.search(soup.get_text(" ", strip=True))
            if date_match:
                raw = date_match.group(0)
        if not raw:
            return ""
        iso_date = _parse_human_date(raw)
        if not iso_date:
            try:
                iso_date = (
                    datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
                )
            except ValueError:
                return ""
        return iso_date + "T00:00:00+00:00"

    def _extract_categories(self, soup: BeautifulSoup) -> list[str]:
        for caption in soup.find_all(
            string=lambda value: value and value.strip() == "Category"
        ):
            item = caption.parent.find_parent("li") if caption.parent else None
            if item:
                categories = [
                    re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
                    for a in item.select('a[href*="/blog/category/"]')
                    if a.get_text(" ", strip=True)
                ]
                if categories:
                    return categories
        return []
