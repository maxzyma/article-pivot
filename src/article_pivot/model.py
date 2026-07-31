from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SCHEMA_VERSION = "article.v1"


@dataclass(frozen=True)
class InlineNode:
    type: str
    text: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)
    children: tuple["InlineNode", ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "InlineNode":
        return cls(
            type=value["type"],
            text=value.get("text", ""),
            attrs=dict(value.get("attrs", {})),
            children=tuple(cls.from_dict(child) for child in value.get("children", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.text:
            result["text"] = self.text
        if self.attrs:
            result["attrs"] = self.attrs
        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
        return result


@dataclass(frozen=True)
class Block:
    id: str
    type: str
    inlines: tuple[InlineNode, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)
    children: tuple["Block", ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Block":
        return cls(
            id=value["id"],
            type=value["type"],
            inlines=tuple(InlineNode.from_dict(node) for node in value.get("inlines", [])),
            attrs=dict(value.get("attrs", {})),
            children=tuple(cls.from_dict(child) for child in value.get("children", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"id": self.id, "type": self.type}
        if self.inlines:
            result["inlines"] = [node.to_dict() for node in self.inlines]
        if self.attrs:
            result["attrs"] = self.attrs
        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
        return result

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True)
class CanonicalDocument:
    document_id: str
    source: dict[str, Any]
    revision: dict[str, Any]
    title: str
    blocks: tuple[Block, ...]
    title_en: str = ""
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    assets: tuple[dict[str, Any], ...] = ()
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CanonicalDocument":
        content = value.get("content", {})
        return cls(
            document_id=value["document_id"],
            source=dict(value["source"]),
            revision=dict(value["revision"]),
            title=content["title"],
            title_en=content.get("title_en", ""),
            summary=content.get("summary", ""),
            blocks=tuple(Block.from_dict(block) for block in content.get("blocks", [])),
            metadata=dict(value.get("metadata", {})),
            assets=tuple(value.get("assets", [])),
            schema_version=value.get("schema_version", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "document_id": self.document_id,
            "source": self.source,
            "revision": self.revision,
            "content": {
                "title": self.title,
                "title_en": self.title_en,
                "summary": self.summary,
                "blocks": [block.to_dict() for block in self.blocks],
            },
            "metadata": self.metadata,
            "assets": list(self.assets),
        }

    def all_blocks(self) -> tuple[Block, ...]:
        return tuple(block for root in self.blocks for block in root.walk())


@dataclass(frozen=True)
class TranslationSegment:
    block_id: str
    inlines: tuple[InlineNode, ...]
    status: str = "translated"
    attrs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, block_id: str, value: dict[str, Any]) -> "TranslationSegment":
        return cls(
            block_id=block_id,
            inlines=tuple(InlineNode.from_dict(node) for node in value.get("inlines", [])),
            status=value.get("status", "translated"),
            attrs=dict(value.get("attrs", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "status": self.status,
            "inlines": [node.to_dict() for node in self.inlines],
        }
        if self.attrs:
            result["attrs"] = self.attrs
        return result


@dataclass(frozen=True)
class TranslationOverlay:
    locale: str
    source_revision: str
    segments: dict[str, TranslationSegment]
    engine: str = ""
    prompt_version: str = ""
    title: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TranslationOverlay":
        return cls(
            locale=value["locale"],
            source_revision=value["source_revision"],
            engine=value.get("engine", ""),
            prompt_version=value.get("prompt_version", ""),
            title=value.get("title", ""),
            segments={
                block_id: TranslationSegment.from_dict(block_id, segment)
                for block_id, segment in value.get("segments", {}).items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "locale": self.locale,
            "source_revision": self.source_revision,
            "engine": self.engine,
            "prompt_version": self.prompt_version,
            "title": self.title,
            "segments": {
                block_id: segment.to_dict() for block_id, segment in self.segments.items()
            },
        }


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    translation: str
    note: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GlossaryEntry":
        return cls(
            term=value["term"],
            translation=value["translation"],
            note=value.get("note", ""),
        )

    def to_dict(self) -> dict[str, str]:
        result = {"term": self.term, "translation": self.translation}
        if self.note:
            result["note"] = self.note
        return result


@dataclass(frozen=True)
class EditorialOverlay:
    locale: str
    source_revision: str
    profile: str
    category: str
    key_points: tuple[str, ...]
    glossary: tuple[GlossaryEntry, ...]
    source_label: str = ""
    summary: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EditorialOverlay":
        return cls(
            locale=value["locale"],
            source_revision=value["source_revision"],
            profile=value["profile"],
            category=value.get("category", ""),
            key_points=tuple(value.get("key_points", [])),
            glossary=tuple(GlossaryEntry.from_dict(item) for item in value.get("glossary", [])),
            source_label=value.get("source_label", ""),
            summary=value.get("summary", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "locale": self.locale,
            "source_revision": self.source_revision,
            "profile": self.profile,
            "category": self.category,
            "summary": self.summary,
            "source_label": self.source_label,
            "key_points": list(self.key_points),
            "glossary": [entry.to_dict() for entry in self.glossary],
        }
