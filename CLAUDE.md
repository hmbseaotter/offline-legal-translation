# Offline legal translation kit

Scripts that drive a **local** language model (Ollama, `gams3:q8`) to produce
draft translations of legal documents, EN↔SL, later DE.

---

## ⛔ HARD BOUNDARY — READ FIRST

**Confidential case material must never enter a Claude Code session.**

The documents this pipeline processes relate to a pending criminal
prosecution and are subject to a confidentiality obligation. Claude Code
runs locally but sends context to Anthropic's servers for inference. Any
document content read into a session — via Read, Grep, `cat`, `head`,
`pdftotext`, a script that echoes file contents, or a pasted error message
containing a document excerpt — **leaves the premises**. That is the exact
thing this project exists to prevent.

### The rule

| Path | Claude Code may touch it |
|---|---|
| `~/Claude_Stuff/cli_projects/` | Yes — all Claude Code CLI work lives here |
| `…/translation-tools/` (this repo) | Yes — scripts, config, fixtures |
| `…/translation-tools/fixtures/` | Yes — synthetic, invented content |
| `~/translation-work/docs/` | Yes — reference documents, no case content |
| `~/translation-work/confidential-projects/` | **NO — the entire tree** |
| …/`<project>/source/`, `translated/`, `work/`, `logs/` | **NO** |
| …/`<project>/glossary/project.tsv` | Ask the operator — case-specific |
| …/`_shared/` | Ask the operator — general terminology, usually fine |

The container mounts at `~/translation-work/confidential-projects/`. When it
is closed that path is empty, which is the desired state during any session.

### Practical consequences

- **Always start from this directory:** `cd $KIT && claude`, where
  `KIT=~/Claude_Stuff/cli_projects/translation-tools`.
  Never launch from `~` or from anywhere under `~/translation-work/`.
  The guard enforces this, but do not rely on it — see the handover doc.
- **Develop against fixtures only.** Run `tr-fixtures` to generate synthetic
  Slovene legal documents. They exercise every hard case (abbreviations,
  case numbers, diacritics, high-repeat tables) without any real data.
- **Never run `tr-run` against a real project inside a session.**
  Batch runs are operator-only, in a plain terminal with no assistant
  attached.
- **If a real document is needed to reproduce a bug,** the operator
  hand-redacts an excerpt or reproduces the structure synthetically.
  Do not ask for the original.
- **Do not `cat` log files.** Ask the operator to paste the specific
  non-content line (an exception, a path, a count).

If a task appears to require reading case material, stop and say so.
The correct response is to redesign the task, not to read the file.

---

## Layout

```
~/Claude_Stuff/cli_projects/
  translation-tools/                 this repo — no case data, ever
    bin/  lib/  glossary/  prompts/
    fixtures/                        synthetic test docs (gitignored)

~/translation-work/
  docs/                              reference manuals. Readable.
  confidential-projects/             DATA — encrypted container mounts here
    _shared/glossary/base.tsv        terminology reusable across matters
    _shared/prompts/translate.txt
    .active                          which project the tools operate on
    <project>/source/  translated/  work/  logs/  glossary/project.tsv
```

## Tools

| Command | Purpose |
|---|---|
| `case-init` / `case-open` / `case-close` / `case-status` | Encrypted container |
| `tr-project [--new] <name>` | List, create, or switch the active project |
| `tr-setup` | One-time provisioning. Idempotent. |
| `tr-model` | Register the GGUF with Ollama as `gams3:q8` |
| `tr-fixtures [dir]` | Generate synthetic test documents |
| `tr-status` | Diff `source/` against `translated/` |
| `tr-run [-n] [file]` | Batch translate; resumable |
| `tr-docx` / `tr-xlsx` / `tr-pdf` / `tr-txt` | Per-format workers |
| `tr-lint` | Deterministic checks over the memory |

## Design invariants

Do not change these without discussing with the operator first.

1. **Filenames are preserved** from `source/` to `translated/`. This is a
   client requirement and the basis of `tr-status`. Optional `TR_SUFFIX`.
2. **Segment granularity is the sentence**, because that is the reviewer's
   unit of work and it makes the memory reusable across documents.
3. **Abbreviations must not split sentences.** `ABBREV` in `lib/trlib.py`
   holds the Slovene legal list (`št.` `čl.` `odst.` `d.o.o.` …). Adding
   entries is expected; removing them breaks review ergonomics.
4. **Non-translatables pass through verbatim** — case numbers, dates,
   amounts, statute short forms. Patterns in `glossary/nontranslatable.txt`.
5. **The memory is the resume state.** `work/tm.sqlite` keys on
   `sha256(direction, model, prompt_version, source)`. Changing the prompt
   must bump `TR_PROMPT_VERSION` or stale translations get reused.
6. **`tr-lint` runs no model.** It must stay deterministic and fast.
7. **Projects are isolated.** Each has its own `work/tm.sqlite`. Translation
   memory must never be shared across matters — different clients, different
   confidentiality obligations. Glossary layers (shared base + project
   overlay); memory does not.

## Testing

```bash
tr-fixtures fixtures/
TR_ROOT=/tmp/trtest tr-xlsx fixtures/dokazi-velika.xlsx --survey
python3 -c "import sys;sys.path.insert(0,'lib');import trlib;print(trlib.segment('Po čl. 211 odst. 2 KZ-1. Sodišče je odločilo.'))"
# expect two segments, not four
```

A mock model server is the right way to test the pipeline without waiting
on real inference — it also keeps iteration fast. See the handover document.
