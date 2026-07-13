from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .model import CanonicalDocument, EditorialOverlay, TranslationOverlay, TranslationSegment


@dataclass(frozen=True)
class CanonicalPackage:
    root: Path
    document: CanonicalDocument
    translations: dict[str, TranslationOverlay]
    editorials: dict[str, EditorialOverlay] = field(default_factory=dict)

    @classmethod
    def load(cls, root: str | Path) -> "CanonicalPackage":
        root_path = Path(root).resolve()
        document_path = root_path / "canonical.json"
        if not document_path.is_file():
            raise ValueError(f"canonical package is missing {document_path}")
        document = CanonicalDocument.from_dict(json.loads(document_path.read_text()))
        translations: dict[str, TranslationOverlay] = {}
        translation_dir = root_path / "translations"
        if translation_dir.is_dir():
            for path in sorted(translation_dir.glob("*.json")):
                overlay = TranslationOverlay.from_dict(json.loads(path.read_text()))
                translations[overlay.locale] = overlay
        editorials: dict[str, EditorialOverlay] = {}
        editorial_dir = root_path / "editorial"
        if editorial_dir.is_dir():
            for path in sorted(editorial_dir.glob("*.json")):
                editorial = EditorialOverlay.from_dict(json.loads(path.read_text()))
                editorials[editorial.locale] = editorial
        return cls(root=root_path, document=document, translations=translations, editorials=editorials)

    def translation(self, locale: str | None) -> TranslationOverlay | None:
        if locale is None:
            return None
        return self.translations.get(locale)

    def editorial(self, locale: str | None) -> EditorialOverlay | None:
        if locale is None:
            return None
        return self.editorials.get(locale)

    def initialize_translation(self, locale: str) -> Path:
        translation_dir = self.root / "translations"
        translation_dir.mkdir(exist_ok=True)
        path = translation_dir / f"{locale}.json"
        if path.exists():
            raise FileExistsError(f"translation overlay already exists: {path}")
        translatable = {
            block.id: TranslationSegment(block_id=block.id, inlines=(), status="pending")
            for block in self.document.all_blocks()
            if block.type in {"heading", "paragraph", "list_item", "table"}
        }
        overlay = TranslationOverlay(
            locale=locale,
            source_revision=self.document.revision["source_hash"],
            segments=translatable,
        )
        path.write_text(json.dumps(overlay.to_dict(), ensure_ascii=False, indent=2) + "\n")
        return path

    @classmethod
    def write(
        cls,
        root: str | Path,
        document: CanonicalDocument,
        raw_html: str = "",
    ) -> "CanonicalPackage":
        root_path = Path(root).resolve()
        root_path.mkdir(parents=True, exist_ok=True)
        (root_path / "canonical.json").write_text(
            json.dumps(document.to_dict(), ensure_ascii=False, indent=2) + "\n"
        )
        if raw_html:
            raw_dir = root_path / "raw"
            raw_dir.mkdir(exist_ok=True)
            (raw_dir / "source.html").write_text(raw_html)
        return cls(root=root_path, document=document, translations={}, editorials={})
