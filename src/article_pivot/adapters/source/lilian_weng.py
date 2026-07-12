from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, NavigableString, Tag

from ...model import Block, CanonicalDocument, InlineNode
from ...validation import ValidationReport, validate_document


DEFAULT_FEED = "https://lilianweng.github.io/index.xml"
ALLOWED_HOST = "lilianweng.github.io"


def _slugify(value: str) -> str:
    value = value.lower().replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


@dataclass(frozen=True)
class DiscoveryItem:
    title: str
    url: str
    published_at: str

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "published_at": self.published_at}


@dataclass(frozen=True)
class RawSnapshot:
    url: str
    fetched_at: str
    html: str
    source_hash: str


class LilianWengDiscovery:
    def discover(self, feed_xml: str, known_urls: Iterable[str] = ()) -> tuple[DiscoveryItem, ...]:
        known = set(known_urls)
        root = ET.fromstring(feed_xml)
        items: list[DiscoveryItem] = []
        for item in root.findall("./channel/item"):
            url = (item.findtext("link") or "").strip()
            if not url or url in known:
                continue
            published = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(timezone.utc)
            items.append(
                DiscoveryItem(
                    title=(item.findtext("title") or "").strip(),
                    url=url,
                    published_at=published.isoformat(),
                )
            )
        return tuple(sorted(items, key=lambda value: value.published_at, reverse=True))

    def fetch(self, url: str = DEFAULT_FEED) -> str:
        return _fetch_text(url, accept="application/rss+xml, application/xml;q=0.9")


class _IdFactory:
    def __init__(self):
        self.counts: Counter[str] = Counter()

    def make(self, block_type: str, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        digest = hashlib.sha256(f"{block_type}\0{normalized}".encode()).hexdigest()[:12]
        key = f"{block_type}-{digest}"
        self.counts[key] += 1
        return key if self.counts[key] == 1 else f"{key}-{self.counts[key]}"


def _fetch_text(url: str, accept: str = "text/html") -> str:
    request = Request(url, headers={"User-Agent": "article-pivot/0.1", "Accept": accept})
    with urlopen(request, timeout=30) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8")


def _inline_nodes(element: Tag, base_url: str) -> tuple[InlineNode, ...]:
    nodes: list[InlineNode] = []
    for child in element.children:
        if isinstance(child, NavigableString):
            if str(child):
                nodes.append(InlineNode(type="text", text=str(child)))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        children = _inline_nodes(child, base_url)
        text = child.get_text(" ", strip=False)
        if name in {"strong", "b"}:
            nodes.append(InlineNode(type="strong", children=children, text=text if not children else ""))
        elif name in {"em", "i"}:
            nodes.append(InlineNode(type="emphasis", children=children, text=text if not children else ""))
        elif name == "code":
            nodes.append(InlineNode(type="inline_code", text=child.get_text()))
        elif name == "a":
            nodes.append(
                InlineNode(
                    type="link",
                    attrs={"url": urljoin(base_url, child.get("href", ""))},
                    children=children,
                    text=text if not children else "",
                )
            )
        elif name == "br":
            nodes.append(InlineNode(type="line_break"))
        else:
            nodes.extend(children or (InlineNode(type="text", text=text),))
    return tuple(nodes)


def _plain_text(inlines: tuple[InlineNode, ...]) -> str:
    def node_text(node: InlineNode) -> str:
        return "".join(node_text(child) for child in node.children) if node.children else node.text

    return "".join(node_text(node) for node in inlines)


class LilianWengAdapter:
    def match(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.netloc == ALLOWED_HOST and parsed.path.startswith("/posts/")

    def fetch(self, url: str) -> RawSnapshot:
        if not self.match(url):
            raise ValueError(f"unsupported Lilian Weng URL: {url}")
        html = _fetch_text(url)
        return RawSnapshot(
            url=url,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            html=html,
            source_hash="sha256:" + hashlib.sha256(html.encode()).hexdigest(),
        )

    def parse(self, snapshot: RawSnapshot) -> CanonicalDocument:
        soup = BeautifulSoup(snapshot.html, "html.parser")
        article = soup.select_one("article.post-single")
        content = article.select_one(".post-content") if article else None
        title_node = article.select_one("h1.post-title") if article else None
        if content is None or title_node is None:
            raise ValueError("Lilian Weng article structure not found")
        title = title_node.get_text(" ", strip=True)
        published_meta = soup.select_one('meta[property="article:published_time"]')
        author_meta = soup.select_one('meta[name="author"]')
        published_at = published_meta.get("content", "") if published_meta else ""
        factory = _IdFactory()
        blocks = tuple(self._parse_children(content, snapshot.url, factory))
        assets = tuple(
            {
                "type": "image",
                "url": block.attrs["url"],
                "alt": block.attrs.get("alt", ""),
            }
            for block in blocks
            if block.type == "image"
        )
        source_slug = urlparse(snapshot.url).path.rstrip("/").split("/")[-1]
        slug = _slugify(title)
        return CanonicalDocument(
            document_id=f"lilian-weng:{source_slug}",
            source={
                "canonical_url": snapshot.url,
                "site": "lilian-weng",
                "author": author_meta.get("content", "Lilian Weng") if author_meta else "Lilian Weng",
                "published_at": published_at,
                "source_timezone": "UTC",
            },
            revision={
                "source_hash": snapshot.source_hash,
                "fetched_at": snapshot.fetched_at,
                "parser_version": "lilian-weng.v1",
            },
            title=title,
            title_en=title,
            blocks=blocks,
            metadata={"slug": slug, "source_slug": source_slug, "source_profile": "lilian-weng.v1"},
            assets=assets,
        )

    def validate(self, document: CanonicalDocument) -> ValidationReport:
        return validate_document(document)

    def _parse_children(self, parent: Tag, base_url: str, factory: _IdFactory):
        for child in parent.children:
            if not isinstance(child, Tag):
                continue
            block = self._parse_block(child, base_url, factory)
            if block is None:
                continue
            if isinstance(block, tuple):
                yield from block
            else:
                yield block

    def _parse_block(self, element: Tag, base_url: str, factory: _IdFactory):
        name = element.name.lower()
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            inlines = _inline_nodes(element, base_url)
            text = _plain_text(inlines)
            return Block(factory.make("heading", text), "heading", inlines, {"level": int(name[1])})
        if name == "p":
            inlines = _inline_nodes(element, base_url)
            text = _plain_text(inlines)
            if not text.strip():
                return None
            return Block(factory.make("paragraph", text), "paragraph", inlines)
        if name in {"ul", "ol"}:
            items = []
            for item in element.find_all("li", recursive=False):
                inlines = _inline_nodes(item, base_url)
                nested = tuple(
                    block
                    for nested_list in item.find_all(["ul", "ol"], recursive=False)
                    for block in (self._parse_block(nested_list, base_url, factory),)
                    if isinstance(block, Block)
                )
                text = _plain_text(inlines)
                items.append(Block(factory.make("list-item", text), "list_item", inlines, children=nested))
            text = "\n".join(_plain_text(item.inlines) for item in items)
            return Block(factory.make("list", text), "list", attrs={"ordered": name == "ol"}, children=tuple(items))
        if name == "blockquote":
            children = tuple(self._parse_children(element, base_url, factory))
            text = element.get_text(" ", strip=True)
            return Block(factory.make("blockquote", text), "blockquote", children=children)
        if name == "pre":
            code = element.get_text().rstrip("\n")
            code_node = element.find("code")
            classes = code_node.get("class", []) if code_node else []
            language = next((value.removeprefix("language-") for value in classes if value.startswith("language-")), "")
            return Block(factory.make("code", code), "code", attrs={"code": code, "language": language})
        if name == "figure":
            image = element.find("img")
            if image is None:
                return None
            url = urljoin(base_url, image.get("src", ""))
            caption = element.find("figcaption")
            alt = image.get("alt", "") or (caption.get_text(" ", strip=True) if caption else "")
            return Block(factory.make("image", url), "image", attrs={"url": url, "alt": alt})
        if name == "table":
            rows = [[cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])] for row in element.find_all("tr")]
            headers = rows[0] if rows and element.find("th") else []
            body = rows[1:] if headers else rows
            text = "\n".join("\t".join(row) for row in rows)
            return Block(factory.make("table", text), "table", attrs={"headers": headers, "rows": body})
        if name == "div" and (element.find("pre") or "highlight" in element.get("class", [])):
            pre = element.find("pre")
            return self._parse_block(pre, base_url, factory) if pre else None
        nested = tuple(self._parse_children(element, base_url, factory))
        return nested or None
