# Article Pivot

Article Pivot is a reusable library and CLI for converting source articles
into versioned canonical documents and target-specific archive or publication
artifacts.

The project owns deterministic content processing and adapter contracts. Agent
skills are thin interaction layers, content repositories are archive targets,
and private automation owns credentials, schedules, routing, and runtime state.

## Initial scope

- Versioned canonical article model with stable block identifiers.
- Structural validation for headings, code, math, links, and translations.
- Chinese-first bilingual Markdown rendering.
- Versioned editorial overlays and a shared `bilingual-zh-first.v1`
  publication document for local and platform renderers.
- Dry-run-first archive adapter for `trending-diggest` repositories.
- RSS discovery and canonical extraction for new Lilian Weng posts.
- Dated notes archive planning with overwrite protection.
- Contract and regression tests for historical formatting failures.

The first release does not replace existing production schedulers. Migration is
expected to use parallel dry-runs before publishing ownership is switched.

## 安装

Article Pivot currently requires Python 3.11 or newer. Install the local
checkout in editable mode while the public API is stabilizing:

```bash
python3 -m pip install -e .
```

## 使用

Validate and render a canonical package:

```bash
article-pivot validate examples/harness
article-pivot render examples/harness --output /tmp/article.md
```

Plan an archive write without mutating the target repository:

```bash
article-pivot archive-trending \
  examples/harness \
  --repo /path/to/trending-diggest \
  --source claude-blog \
  --dry-run
```

Remove `--dry-run` only after reviewing the plan. Archive operations never
commit or push implicitly.

Process a new Lilian Weng post:

```bash
article-pivot discover-lilian --known-url <already-processed-url>
article-pivot fetch-lilian <post-url> --output /path/to/package
article-pivot init-translation /path/to/package --locale zh-CN
article-pivot validate /path/to/package --locale zh-CN
article-pivot archive-notes /path/to/package \
  --repo /path/to/notes-repo \
  --locale zh-CN \
  --dry-run
```

`init-translation` deliberately creates pending segments. A translator must
fill every segment and the translated title before validation and rendering.
Publication packages also provide `editorial/<locale>.json` with the category,
key points, glossary, source label, and `bilingual-zh-first.v1` profile. When
present, both preview and archive rendering use the same fixed structure:
metadata, key points, body, and glossary. Platform publishers must derive from
that publication document and limit changes to target capability adaptations.
The notes adapter refuses to overwrite an existing article directory.

New Lilian Weng posts use this flow. Claude Blog remains on its legacy
`claude-blog-digest` producer until that source completes separate migration
gates; these commands do not change its scheduler or production writer.

## Repository boundary

`trending-diggest` is a public archive and reading site. It owns its public
front matter, paths, indexes, and site build. It does not own extraction,
translation, credentials, scheduler state, or DingTalk delivery.
