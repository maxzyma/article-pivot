from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters.archive import TrendingDigestArchiveAdapter
from .package import CanonicalPackage
from .renderers import render_bilingual_markdown
from .validation import validate_document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="article-pipeline")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate a canonical package")
    validate.add_argument("package")
    validate.add_argument("--locale", default="zh-CN")

    render = commands.add_parser("render", help="render bilingual Markdown")
    render.add_argument("package")
    render.add_argument("--locale", default="zh-CN")
    render.add_argument("--output", required=True)

    archive = commands.add_parser("archive-trending", help="archive into trending-diggest")
    archive.add_argument("package")
    archive.add_argument("--repo", required=True)
    archive.add_argument("--source", required=True)
    archive.add_argument("--locale", default="zh-CN")
    archive.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    package = CanonicalPackage.load(args.package)
    overlay = package.translation(args.locale)

    if args.command == "validate":
        report = validate_document(package.document, overlay)
        print(json.dumps({"ok": report.ok, "issues": [issue.__dict__ for issue in report.issues]}, ensure_ascii=False, indent=2))
        return 0 if report.ok else 1

    if args.command == "render":
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_bilingual_markdown(package, locale=args.locale))
        print(output.resolve())
        return 0

    adapter = TrendingDigestArchiveAdapter(args.repo)
    plan = adapter.plan(package, source_key=args.source, locale=args.locale)
    if args.dry_run:
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        return 0
    receipt = adapter.write(plan)
    adapter.verify(receipt)
    print(json.dumps({"post_path": str(receipt.post_path), "manifest_path": str(receipt.manifest_path), "index_path": str(receipt.index_path), "content_sha256": receipt.content_sha256, "manifest_sha256": receipt.manifest_sha256, "index_sha256": receipt.index_sha256}, ensure_ascii=False, indent=2))
    return 0
