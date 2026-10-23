# Report source format

`source.md` is one source that renders three editions of the same report. Editing it and
re-running `render/render.sh` regenerates all three, so they never disagree with each other.

| Edition | Target length | Rough body text |
|---|---|---|
| Short (S) | about 6–10 pages | 2,400–3,800 words |
| Medium (M) | about 12–18 pages | 5,000–7,000 words |
| Long (L) | about 20–30 pages | 8,000–12,500 words |

Page targets count body pages; the title page and the contents page come on top. Layout is US
Letter, 11 pt body, 1 inch margins.

## Front matter

The file starts with a block like this:

```
---
title: <repo> — Architecture and Workflow Report
short_title: <repo>
subtitle: One-line description of the repository
repo: https://github.com/<owner>/<repo>
commit: <short SHA the report was checked against>
date: <YYYY-MM-DD the report was checked>
---
```

`short_title` is used in file names and in the footer: `<short_title>  |  Page X of Y`.
Update `commit` and `date` whenever the report is re-checked against the code.

## Edition blocks

Untagged content appears in every edition. Fenced blocks limit content to some editions:

```
::: M
shown in Medium and Long
:::

::: L
shown only in Long
:::

::: S-only
shown only in Short (a condensed passage that M and L replace with detail)
:::

::: SM-only
shown in Short and Medium, not Long (a summary that L replaces with fuller text)
:::
```

Blocks do not nest, and a block may hold whole sections. Write the Short content as the spine,
readable on its own, then deepen it with M and L blocks. An untagged passage must never refer to
something that exists only in a Medium or Long block.

## Supported markup

- `#`, `##` and `###` headings. Do not number them; the renderer does.
- Paragraphs with `**bold**`, `*italic*` and `` `code` ``. Write links as plain URLs.
- Bullet lists (`- item`, one nested level with two spaces) and numbered lists (`1. item`).
- Pipe tables with a header row and a `|---|` separator. Keep to four columns or fewer.
- Fenced code blocks for commands and short excerpts.
- Figures: `![Caption text](diagrams/name.dot)` on a line of its own. The renderer turns the
  Graphviz file into an image; the caption is numbered automatically.
- A line starting with `> ` becomes a shaded note box.

## Diagrams

Diagrams are Graphviz files in `diagrams/`. Keep them under about 18 nodes so they stay legible
at page width, use short labels, and check that each one renders with `dot -Tpng`.

## Section skeleton

1. Executive summary
2. Context and problem
3. Repository map
4. Architecture
5. Components in detail
6. How it works: logical description and data model
7. Workflows
8. Companion repositories (where they exist)
9. Running it
10. Assessment (the report author's observations, kept separate from description)
11. Glossary (Medium and Long)
12. Appendix (Long only)

Write for a technical reader with no prior knowledge of the repository. Define each
project-specific term on first use, and check every factual claim against the code rather than
against the repository's own prose.
