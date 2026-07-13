from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .model import Block, EditorialOverlay, GlossaryEntry, TranslationOverlay
from .package import CanonicalPackage
from .validation import validate_document


PUBLICATION_PROFILE = "bilingual-zh-first.v1"


@dataclass(frozen=True)
class PublicationEntry:
    original: Block
    translated: Block | None


@dataclass(frozen=True)
class PublicationDocument:
    profile: str
    locale: str
    title: str
    original_title: str
    source_label: str
    source_url: str
    published_date: str
    category: str
    key_points: tuple[str, ...]
    body: tuple[PublicationEntry, ...]
    glossary: tuple[GlossaryEntry, ...]


def _apply_overlay(block: Block, overlay: TranslationOverlay) -> Block:
    segment = overlay.segments.get(block.id)
    return Block(
        id=block.id,
        type=block.type,
        inlines=segment.inlines if segment else block.inlines,
        attrs=segment.attrs if segment and segment.attrs else block.attrs,
        children=tuple(_apply_overlay(child, overlay) for child in block.children),
    )


def _validate_editorial(package: CanonicalPackage, editorial: EditorialOverlay) -> None:
    if editorial.profile != PUBLICATION_PROFILE:
        raise ValueError(f"unsupported publication profile: {editorial.profile}")
    if editorial.source_revision != package.document.revision["source_hash"]:
        raise ValueError("editorial overlay source revision does not match canonical document")
    if not editorial.category.strip():
        raise ValueError("publication category is required")
    if not editorial.key_points:
        raise ValueError("publication key points are required")
    if not editorial.glossary:
        raise ValueError("publication glossary is required")


def build_publication_document(
    package: CanonicalPackage,
    locale: str = "zh-CN",
) -> PublicationDocument:
    translation = package.translation(locale)
    editorial = package.editorial(locale)
    if translation is None:
        raise ValueError(f"translation overlay is required for locale {locale}")
    if editorial is None:
        raise ValueError(f"editorial overlay is required for locale {locale}")
    validate_document(package.document, translation).require_ok()
    _validate_editorial(package, editorial)

    published = str(package.document.source.get("published_at", ""))
    try:
        published_date = datetime.fromisoformat(published.replace("Z", "+00:00")).date().isoformat()
    except ValueError as exc:
        raise ValueError("source.published_at must be ISO 8601") from exc
    entries = []
    for block in package.document.blocks:
        has_translation = any(item.id in translation.segments for item in block.walk())
        translated = _apply_overlay(block, translation) if has_translation else None
        entries.append(PublicationEntry(original=block, translated=translated))
    source_label = editorial.source_label or (
        f"Lil'Log / {package.document.source.get('author', 'Lilian Weng')}"
    )
    return PublicationDocument(
        profile=editorial.profile,
        locale=locale,
        title=translation.title or package.document.title,
        original_title=package.document.title_en or package.document.title,
        source_label=source_label,
        source_url=package.document.source["canonical_url"],
        published_date=published_date,
        category=editorial.category,
        key_points=editorial.key_points,
        body=tuple(entries),
        glossary=editorial.glossary,
    )


def publication_document_title(publication: PublicationDocument) -> str:
    return f"{publication.published_date} {publication.title}"
