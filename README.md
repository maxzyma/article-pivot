# Article Pipeline

Article Pipeline is a reusable library and CLI for converting source articles
into versioned canonical documents and target-specific archive or publication
artifacts.

The project owns deterministic content processing and adapter contracts. Agent
skills are thin interaction layers, content repositories are archive targets,
and private automation owns credentials, schedules, routing, and runtime state.

## Initial scope

- Versioned canonical article model with stable block identifiers.
- Structural validation for headings, code, math, links, and translations.
- Chinese-first bilingual Markdown rendering.
- Dry-run-first archive adapter for `trending-diggest` repositories.
- Contract and regression tests for historical formatting failures.

The first release does not replace existing production schedulers. Migration is
expected to use parallel dry-runs before publishing ownership is switched.

## 安装

Article Pipeline currently requires Python 3.11 or newer. Install the local
checkout in editable mode while the public API is stabilizing:

```bash
python3 -m pip install -e .
```

## 使用

Validate and render a canonical package:

```bash
article-pipeline validate examples/harness
article-pipeline render examples/harness --output /tmp/article.md
```

Plan an archive write without mutating the target repository:

```bash
article-pipeline archive-trending \
  examples/harness \
  --repo /path/to/trending-diggest \
  --source claude-blog \
  --dry-run
```

Remove `--dry-run` only after reviewing the plan. Archive operations never
commit or push implicitly.

## Repository boundary

`trending-diggest` is a public archive and reading site. It owns its public
front matter, paths, indexes, and site build. It does not own extraction,
translation, credentials, scheduler state, or DingTalk delivery.
