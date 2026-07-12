from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters.archive import DatedNotesArchiveAdapter, TrendingDigestArchiveAdapter
from .adapters.source import LilianWengAdapter, LilianWengDiscovery
from .package import CanonicalPackage
from .renderers import render_bilingual_markdown
from .validation import validate_document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="article-pivot")
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

    discover = commands.add_parser("discover-lilian", help="discover Lilian Weng posts from RSS")
    discover.add_argument("--feed", default="https://lilianweng.github.io/index.xml")
    discover.add_argument("--known-url", action="append", default=[])

    fetch = commands.add_parser("fetch-lilian", help="fetch a Lilian Weng post into a canonical package")
    fetch.add_argument("url")
    fetch.add_argument("--output", required=True)

    initialize = commands.add_parser("init-translation", help="create a pending translation overlay")
    initialize.add_argument("package")
    initialize.add_argument("--locale", default="zh-CN")

    notes = commands.add_parser("archive-notes", help="archive into a dated Markdown article library")
    notes.add_argument("package")
    notes.add_argument("--repo", required=True)
    notes.add_argument("--locale", default="zh-CN")
    notes.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "discover-lilian":
        discovery = LilianWengDiscovery()
        items = discovery.discover(discovery.fetch(args.feed), known_urls=args.known_url)
        print(json.dumps({"items": [item.to_dict() for item in items]}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "fetch-lilian":
        adapter = LilianWengAdapter()
        snapshot = adapter.fetch(args.url)
        document = adapter.parse(snapshot)
        adapter.validate(document).require_ok()
        package = CanonicalPackage.write(args.output, document, raw_html=snapshot.html)
        print(json.dumps({"package": str(package.root), "document_id": document.document_id, "source_hash": document.revision["source_hash"], "blocks": len(document.all_blocks()), "assets": len(document.assets)}, ensure_ascii=False, indent=2))
        return 0

    package = CanonicalPackage.load(args.package)

    if args.command == "init-translation":
        print(package.initialize_translation(args.locale))
        return 0

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

    if args.command == "archive-notes":
        validate_document(package.document, overlay).require_ok()
        adapter = DatedNotesArchiveAdapter(args.repo)
        plan = adapter.plan(package, locale=args.locale)
        if args.dry_run:
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
            return 0
        adapter.write(plan, package)
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
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
