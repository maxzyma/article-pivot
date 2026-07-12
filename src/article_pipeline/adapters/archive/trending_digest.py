from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from ...package import CanonicalPackage
from ...renderers import render_bilingual_markdown


def _slugify(value: str) -> str:
    original = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", original).strip("-")
    if normalized:
        return normalized
    return hashlib.sha256(original.encode()).hexdigest()[:12]


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _markdown_cell(value: str) -> str:
    return value.replace("\n", " ").replace("|", "\\|").strip()


@dataclass(frozen=True)
class ArchivePlan:
    source_key: str
    post_path: Path
    manifest_path: Path
    index_path: Path
    content: str
    index_content: str
    manifest_entry: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "source_key": self.source_key,
            "post_path": str(self.post_path),
            "manifest_path": str(self.manifest_path),
            "index_path": str(self.index_path),
            "content_sha256": hashlib.sha256(self.content.encode()).hexdigest(),
            "manifest_entry": self.manifest_entry,
        }


@dataclass(frozen=True)
class ArchiveReceipt:
    post_path: Path
    manifest_path: Path
    index_path: Path
    document_id: str
    source_url: str
    source_revision: str
    content_sha256: str
    manifest_sha256: str
    index_sha256: str


class TrendingDigestArchiveAdapter:
    def __init__(self, repo: str | Path):
        self.repo = Path(repo).resolve()

    def plan(
        self,
        package: CanonicalPackage,
        source_key: str,
        locale: str = "zh-CN",
    ) -> ArchivePlan:
        if not (self.repo / "sources").is_dir() or not (self.repo / "README.md").is_file():
            raise ValueError(f"not a trending-diggest repository: {self.repo}")
        document = package.document
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", source_key):
            raise ValueError("source_key must contain lowercase letters, digits, and hyphens")
        published = document.source.get("published_at", "")
        if not published:
            raise ValueError("source.published_at is required for trending-diggest")
        try:
            published_date = datetime.fromisoformat(published.replace("Z", "+00:00")).date()
        except ValueError as exc:
            raise ValueError("source.published_at must be ISO 8601") from exc
        source_url = document.source["canonical_url"]
        url_slug = Path(urlparse(source_url).path.rstrip("/")).name
        slug = document.metadata.get("slug") or _slugify(url_slug or document.title_en or document.title)
        relative_post = Path("sources") / source_key / "posts" / f"{published_date:%Y}" / f"{published_date:%m}" / f"{published_date}-{slug}.md"
        body = render_bilingual_markdown(package, locale=locale)
        frontmatter = "\n".join(
            [
                "---",
                f"source: {_yaml_string(source_key)}",
                f"document_id: {_yaml_string(document.document_id)}",
                f"source_url: {_yaml_string(source_url)}",
                f"source_revision: {_yaml_string(document.revision['source_hash'])}",
                f"title_zh: {_yaml_string(document.title)}",
                f"title_en: {_yaml_string(document.title_en)}",
                f"published_at: {_yaml_string(published_date.isoformat())}",
                "format: \"bilingual-paragraph-zh-first\"",
                "generator: \"article-pipeline@0.1.0\"",
                "---",
                "",
            ]
        )
        manifest_path = self.repo / "sources" / source_key / "manifest.json"
        index_path = self.repo / "sources" / source_key / "index.md"
        relative_link = relative_post.relative_to(Path("sources") / source_key).as_posix()
        category = _markdown_cell(str(document.metadata.get("category", document.source.get("category", ""))))
        row = (
            f"| {published_date.isoformat()} | {_markdown_cell(document.title)} | {category} | "
            f"[Markdown]({relative_link}) | [原文]({source_url}) |"
        )
        if index_path.is_file():
            lines = index_path.read_text().splitlines()
            header_end = next(
                (index for index, line in enumerate(lines) if line.startswith("|---")),
                None,
            )
            if header_end is None:
                raise ValueError(f"unsupported source index format: {index_path}")
            prefix = lines[: header_end + 1]
            rows = [
                line
                for line in lines[header_end + 1 :]
                if line.startswith("|") and source_url not in line and relative_link not in line
            ]
            rows.append(row)
            rows.sort(key=lambda line: line.split("|", 3)[1].strip(), reverse=True)
            index_content = "\n".join(prefix + rows) + "\n"
        else:
            index_content = (
                f"# {source_key}\n\n"
                "公开中文译读归档。\n\n"
                "| 日期 | 标题 | 分类 | 中文译读 | 原文 |\n"
                "|---|---|---|---|---|\n"
                f"{row}\n"
            )
        entry = {
            "document_id": document.document_id,
            "source_url": source_url,
            "source_revision": document.revision["source_hash"],
            "archive_path": str(relative_post),
            "published_at": published_date.isoformat(),
            "generator_version": "article-pipeline@0.1.0",
        }
        post_path = self.repo / relative_post
        if post_path.is_file():
            match = re.search(r'^document_id:\s*(.+)$', post_path.read_text(), re.MULTILINE)
            existing_id = json.loads(match.group(1)) if match else ""
            if existing_id and existing_id != document.document_id:
                raise ValueError(
                    f"archive path collision: {post_path} belongs to {existing_id}"
                )
        return ArchivePlan(
            source_key=source_key,
            post_path=post_path,
            manifest_path=manifest_path,
            index_path=index_path,
            content=frontmatter + body,
            index_content=index_content,
            manifest_entry=entry,
        )

    def write(self, plan: ArchivePlan) -> ArchiveReceipt:
        plan.post_path.parent.mkdir(parents=True, exist_ok=True)
        existing_manifest = {"schema_version": "archive-manifest.v1", "documents": []}
        if plan.manifest_path.is_file():
            existing_manifest = json.loads(plan.manifest_path.read_text())
        documents = {
            item["document_id"]: item for item in existing_manifest.get("documents", [])
        }
        documents[plan.manifest_entry["document_id"]] = plan.manifest_entry
        new_manifest = {
            "schema_version": "archive-manifest.v1",
            "documents": sorted(
                documents.values(),
                key=lambda item: (item["published_at"], item["document_id"]),
                reverse=True,
            ),
        }

        manifest_content = json.dumps(new_manifest, ensure_ascii=False, indent=2) + "\n"
        post_tmp = plan.post_path.with_suffix(plan.post_path.suffix + ".tmp")
        manifest_tmp = plan.manifest_path.with_suffix(".json.tmp")
        index_tmp = plan.index_path.with_suffix(".md.tmp")
        post_tmp.write_text(plan.content)
        manifest_tmp.write_text(manifest_content)
        index_tmp.write_text(plan.index_content)
        operations = (
            (post_tmp, plan.post_path),
            (manifest_tmp, plan.manifest_path),
            (index_tmp, plan.index_path),
        )
        previous = {
            target: target.read_bytes() if target.is_file() else None
            for _, target in operations
        }
        try:
            for staged, target in operations:
                staged.replace(target)
        except Exception:
            for _, target in operations:
                old_content = previous[target]
                if old_content is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(old_content)
            raise
        finally:
            for staged, _ in operations:
                staged.unlink(missing_ok=True)
        return ArchiveReceipt(
            post_path=plan.post_path,
            manifest_path=plan.manifest_path,
            index_path=plan.index_path,
            document_id=plan.manifest_entry["document_id"],
            source_url=plan.manifest_entry["source_url"],
            source_revision=plan.manifest_entry["source_revision"],
            content_sha256=hashlib.sha256(plan.content.encode()).hexdigest(),
            manifest_sha256=hashlib.sha256(manifest_content.encode()).hexdigest(),
            index_sha256=hashlib.sha256(plan.index_content.encode()).hexdigest(),
        )

    def verify(self, receipt: ArchiveReceipt) -> None:
        if not all(path.is_file() for path in (receipt.post_path, receipt.manifest_path, receipt.index_path)):
            raise ValueError("archive receipt points to missing files")
        actual_hash = hashlib.sha256(receipt.post_path.read_bytes()).hexdigest()
        if actual_hash != receipt.content_sha256:
            raise ValueError("archived post hash does not match receipt")
        manifest_hash = hashlib.sha256(receipt.manifest_path.read_bytes()).hexdigest()
        if manifest_hash != receipt.manifest_sha256:
            raise ValueError("archive manifest hash does not match receipt")
        index_hash = hashlib.sha256(receipt.index_path.read_bytes()).hexdigest()
        if index_hash != receipt.index_sha256:
            raise ValueError("archive index hash does not match receipt")
        manifest = json.loads(receipt.manifest_path.read_text())
        entry = next(
            (item for item in manifest.get("documents", []) if item.get("document_id") == receipt.document_id),
            None,
        )
        if not entry or entry.get("source_revision") != receipt.source_revision:
            raise ValueError("archive manifest is missing the receipt revision")
        index = receipt.index_path.read_text()
        if receipt.source_url not in index or entry["archive_path"].split("/", 2)[-1] not in index:
            raise ValueError("archive index is missing the receipt entry")
