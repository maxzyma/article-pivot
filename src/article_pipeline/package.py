from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .model import CanonicalDocument, TranslationOverlay


@dataclass(frozen=True)
class CanonicalPackage:
    root: Path
    document: CanonicalDocument
    translations: dict[str, TranslationOverlay]

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
        return cls(root=root_path, document=document, translations=translations)

    def translation(self, locale: str | None) -> TranslationOverlay | None:
        if locale is None:
            return None
        return self.translations.get(locale)

