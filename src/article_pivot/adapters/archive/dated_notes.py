from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ...package import CanonicalPackage
from ...renderers import render_bilingual_markdown, render_source_markdown


@dataclass(frozen=True)
class NotesArchivePlan:
    article_dir: Path
    source_path: Path
    bilingual_path: Path | None
    canonical_path: Path
    translation_path: Path | None
    editorial_path: Path | None
    raw_path: Path | None
    metadata_path: Path
    index_path: Path
    source_content: str
    bilingual_content: str
    metadata_content: str
    translation_content: str
    editorial_content: str
    index_content: str

    def to_dict(self) -> dict[str, object]:
        return {
            "article_dir": str(self.article_dir),
            "source_path": str(self.source_path),
            "bilingual_path": str(self.bilingual_path) if self.bilingual_path else None,
            "canonical_path": str(self.canonical_path),
            "translation_path": str(self.translation_path) if self.translation_path else None,
            "editorial_path": str(self.editorial_path) if self.editorial_path else None,
            "raw_path": str(self.raw_path) if self.raw_path else None,
            "metadata_path": str(self.metadata_path),
            "index_path": str(self.index_path),
        }


class DatedNotesArchiveAdapter:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def plan(self, package: CanonicalPackage, locale: str = "zh-CN") -> NotesArchivePlan:
        if not (self.root / "article-index.md").is_file():
            raise ValueError(f"not a dated article archive: {self.root}")
        document = package.document
        date = datetime.fromisoformat(document.source["published_at"].replace("Z", "+00:00")).date()
        slug = str(document.metadata.get("slug") or document.document_id.split(":", 1)[-1])
        article_dir = self.root / f"{date:%Y-%m}" / date.isoformat() / slug
        overlay = package.translation(locale)
        editorial = package.editorial(locale)
        display_title = overlay.title if overlay and overlay.title else document.title
        bilingual_path = article_dir / f"{slug}-bilingual.md" if overlay else None
        raw_source = package.root / "raw" / "source.html"
        metadata = {
            "schema_version": "article-archive.v1",
            "document_id": document.document_id,
            "title": display_title,
            "title_zh": display_title if overlay else "",
            "title_en": document.title_en or document.title,
            "source_url": document.source["canonical_url"],
            "author": document.source.get("author", ""),
            "published_at": date.isoformat(),
            "source_revision": document.revision["source_hash"],
            "generator": "article-pivot@0.1.0",
            "canonical_file": "./canonical.json",
            "content_file": f"./{slug}.md",
            "bilingual_file": f"./{slug}-bilingual.md" if overlay else None,
            "translation_file": f"./translations/{locale}.json" if overlay else None,
            "editorial_file": f"./editorial/{locale}.json" if editorial else None,
            "publication_profile": editorial.profile if editorial else None,
        }
        index_path = self.root / "article-index.md"
        relative_link = (article_dir / f"{slug}.md").relative_to(self.root).as_posix()
        row = f"| {date:%m-%d} | [{display_title}]({relative_link}) | Lil'Log / Lilian Weng | `{slug}/` |"
        lines = index_path.read_text().splitlines()
        month_header = f"## {date:%Y-%m}"
        if any(relative_link in line for line in lines):
            index_content = "\n".join(lines) + "\n"
        elif month_header in lines:
            header_index = lines.index(month_header)
            separator_index = next(
                index
                for index in range(header_index + 1, len(lines))
                if lines[index].startswith("|---") or lines[index].startswith("|------")
            )
            lines.insert(separator_index + 1, row)
            index_content = "\n".join(lines) + "\n"
        else:
            section = [
                "",
                month_header,
                "",
                "| 日期 | 标题 | 来源 | 文件路径 |",
                "|------|------|------|----------|",
                row,
            ]
            divider = lines.index("---") + 1 if "---" in lines else len(lines)
            lines[divider:divider] = section
            index_content = "\n".join(lines) + "\n"
        return NotesArchivePlan(
            article_dir=article_dir,
            source_path=article_dir / f"{slug}.md",
            bilingual_path=bilingual_path,
            canonical_path=article_dir / "canonical.json",
            translation_path=article_dir / "translations" / f"{locale}.json" if overlay else None,
            editorial_path=article_dir / "editorial" / f"{locale}.json" if editorial else None,
            raw_path=article_dir / "raw" / "source.html" if raw_source.is_file() else None,
            metadata_path=article_dir / f"{slug}.metadata.json",
            index_path=index_path,
            source_content=render_source_markdown(package),
            bilingual_content=render_bilingual_markdown(package, locale) if overlay else "",
            metadata_content=json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            translation_content=(
                json.dumps(overlay.to_dict(), ensure_ascii=False, indent=2) + "\n" if overlay else ""
            ),
            editorial_content=(
                json.dumps(editorial.to_dict(), ensure_ascii=False, indent=2) + "\n" if editorial else ""
            ),
            index_content=index_content,
        )

    def write(self, plan: NotesArchivePlan, package: CanonicalPackage) -> None:
        if plan.article_dir.exists():
            raise FileExistsError(
                f"archive target already exists; refusing to overwrite: {plan.article_dir}"
            )
        plan.article_dir.mkdir(parents=True, exist_ok=True)
        plan.source_path.write_text(plan.source_content)
        plan.canonical_path.write_text(json.dumps(package.document.to_dict(), ensure_ascii=False, indent=2) + "\n")
        if plan.translation_path:
            plan.translation_path.parent.mkdir(exist_ok=True)
            plan.translation_path.write_text(plan.translation_content)
        if plan.editorial_path:
            plan.editorial_path.parent.mkdir(exist_ok=True)
            plan.editorial_path.write_text(plan.editorial_content)
        plan.metadata_path.write_text(plan.metadata_content)
        plan.index_path.write_text(plan.index_content)
        if plan.bilingual_path:
            plan.bilingual_path.write_text(plan.bilingual_content)
        if plan.raw_path:
            plan.raw_path.parent.mkdir(exist_ok=True)
            plan.raw_path.write_text((package.root / "raw" / "source.html").read_text())
