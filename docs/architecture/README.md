# Architecture report

An explanation of how `offline-legal-translation` is built and how it works, written for a technical reader with no
prior knowledge of the repository: its architecture, the purpose of each component, the logic
behind it, its workflows, how to run it, and an assessment of its strengths and limits.

It comes in three editions rendered from one source, so they never contradict each other:

| Edition | Length | Use it when |
|---|---|---|
| Short | about 6–10 pages | the reader needs the shape of the project and its main workflow |
| Medium | about 12–18 pages | the reader will work with the code or review it |
| Long | about 20–30 pages | the reader needs component-level detail and the appendices |

## What is here

| Path | What it is |
|---|---|
| `source.md` | the report, with edition blocks marking what each edition includes |
| `diagrams/` | the figures, as Graphviz source |
| `FORMAT.md` | how `source.md` is written: front matter, edition blocks, supported markup |
| `render/` | the renderer (`build.js`, `finalize.py`) and `render.sh`, which runs them |

Rendered files are not versioned. They go to `dist/`, which is ignored.

## Rendering

```bash
docs/architecture/render/render.sh            # writes dist/<name>_Report_<Edition>.docx and .pdf
docs/architecture/render/render.sh out/dir    # or to another directory
```

Prerequisites: Node.js, Graphviz (`dot`), LibreOffice with its Python bridge
(`python3 -c "import uno"` must succeed), and `pdfinfo` (Poppler). The `docx` npm package is
installed into `render/node_modules` on first run if Node cannot already find it.

## Keeping it current

The report describes the repository at commit `aea0447`, checked on 2026-10-23. When the code
changes:

1. Edit `source.md` (and any affected diagram), checking each changed claim against the code.
2. Update `commit` and `date` in its front matter.
3. Re-run `render/render.sh` and look over the result.

## How it was produced

The report was drafted from a reading of the code, tests, specifications and history, without
running anything in the repository. It was then fact-checked against the repository by a
separate reviewer, and every finding was resolved before rendering. The Assessment section is
the report author's view, kept apart from the description.
