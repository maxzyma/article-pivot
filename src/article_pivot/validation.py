from __future__ import annotations

from dataclasses import dataclass

from .model import CanonicalDocument, SCHEMA_VERSION, TranslationOverlay


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    block_id: str = ""


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    def require_ok(self) -> None:
        if self.issues:
            details = "; ".join(f"{issue.code}: {issue.message}" for issue in self.issues)
            raise ValueError(details)


def validate_document(
    document: CanonicalDocument,
    overlay: TranslationOverlay | None = None,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    if document.schema_version != SCHEMA_VERSION:
        issues.append(ValidationIssue("schema.version", f"expected {SCHEMA_VERSION}"))
    if not document.document_id.strip():
        issues.append(ValidationIssue("document.id", "document_id is required"))
    if not document.title.strip():
        issues.append(ValidationIssue("content.title", "title is required"))
    if not document.source.get("canonical_url"):
        issues.append(ValidationIssue("source.url", "canonical_url is required"))
    if not document.revision.get("source_hash"):
        issues.append(ValidationIssue("revision.hash", "source_hash is required"))

    block_ids: set[str] = set()
    blocks_by_id = {}
    for block in document.all_blocks():
        if not block.id:
            issues.append(ValidationIssue("block.id", "block id is required"))
        elif block.id in block_ids:
            issues.append(ValidationIssue("block.duplicate", "duplicate block id", block.id))
        block_ids.add(block.id)
        blocks_by_id[block.id] = block
        if block.type == "heading":
            level = block.attrs.get("level")
            if not isinstance(level, int) or level < 1 or level > 6:
                issues.append(ValidationIssue("heading.level", "level must be 1..6", block.id))
        if block.type == "code" and "code" not in block.attrs:
            issues.append(ValidationIssue("code.body", "code block requires attrs.code", block.id))
        if block.type == "math" and "latex" not in block.attrs:
            issues.append(ValidationIssue("math.body", "math block requires attrs.latex", block.id))

    if overlay is not None:
        if overlay.source_revision != document.revision.get("source_hash"):
            issues.append(ValidationIssue("translation.revision", "overlay source revision mismatch"))
        if not overlay.title.strip():
            issues.append(ValidationIssue("translation.title", "translated title is required"))
        unknown = set(overlay.segments) - block_ids
        for block_id in sorted(unknown):
            issues.append(ValidationIssue("translation.unknown_block", "unknown block id", block_id))
        translatable = {
            block.id
            for block in document.all_blocks()
            if block.type in {"heading", "paragraph", "list_item", "table"}
        }
        missing = translatable - set(overlay.segments)
        for block_id in sorted(missing):
            issues.append(ValidationIssue("translation.missing_block", "missing translated block", block_id))
        for block_id in sorted(translatable & set(overlay.segments)):
            segment = overlay.segments[block_id]
            block = blocks_by_id[block_id]
            has_content = bool(segment.attrs) if block.type == "table" else bool(segment.inlines)
            if segment.status != "translated" or not has_content:
                issues.append(ValidationIssue("translation.incomplete_block", "translation is incomplete", block_id))
    return ValidationReport(tuple(issues))
