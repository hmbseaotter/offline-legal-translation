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
| …/`work/inventory/manifest.tsv`, `by-lang/*.txt` | **NO — these are lists of file paths, and a filename in a criminal matter carries party names, dates and case numbers** |
| …/`work/inventory/summary.txt` | **NO — inside the denied tree.** It holds counts and no paths, which is what makes it safe for *the operator* to send to the client. That is a different question from whether a session may read it |
| …/`<project>/glossary/project.tsv` | **NO — inside the denied tree** |
| …/`_shared/` | **NO — inside the denied tree** |
| `~/translation-work/regular-projects/` | **NO — client work, same rule** |

`_shared/` holds general terminology and is the one place where a case-by-case
judgement would be defensible. It is denied anyway, because reaching it at
all requires the container mounted, and the guard refuses to start a session
in that state — so a rule that asked would never have been reached.

The container mounts at `~/translation-work/confidential-projects/`. When it
is closed that path is empty, which is the desired state during any session.
An empty directory there is **not** proof the container exists: until
`case-init` has run it is a plain unencrypted directory. `case-status` is the
only thing that tells you which it is.

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
    bin/  lib/  glossary/  prompts/  tools/  .githooks/
    fixtures/                        synthetic test docs (gitignored)

~/translation-work/
  docs/                              reference manuals. Readable.
  confidential-projects/             DATA — encrypted container mounts here
    _shared/glossary/base.tsv        terminology reusable across matters
    _shared/prompts/translate.txt
    .active                          which project the tools operate on
    <project>/source/                the client drop, nested folders intact
              translated/            same tree, same names
              work/inventory/        manifest.tsv, by-lang/*.txt, summary.txt
              work/  logs/  glossary/project.tsv
```

`source/` holds the client's folder structure exactly as delivered — several
separate drops, nested several levels — and `translated/` mirrors it. Nothing
flattens the tree.

## Tools

| Command | Purpose |
|---|---|
| `case-init` / `case-open` / `case-close` / `case-status` | Encrypted container |
| `tr-project [--new] <name>` | List, create, or switch the active project |
| `tr-setup` | One-time provisioning. Idempotent. |
| `tr-model` | Register the GGUF with Ollama as `gams3:q8` |
| `tr-fixtures [dir]` | Generate synthetic test documents, including a mixed-language drop |
| `tr-inventory` | Classify every file in `source/` by source language. Run this before anything else |
| `tr-inventory --count [--with-ocr]` | Words and segments per file, to size the job before starting. Scanned PDFs need `--with-ocr` |
| `tr-status` | Diff `source/` against `translated/` |
| `tr-run [-n] [--all] [file]` | Batch translate; resumable. Without `--all`, only what the inventory matched |
| `tr-docx` / `tr-xlsx` / `tr-pdf` / `tr-txt` | Per-format workers. `tr-xlsx` also takes `.xlsm` / `.xltx` / `.xltm`, all delivered as `.xlsx` — the translation carries no macros and should not claim to |
| `tr-lint [--tsv F] [--all-versions]` | Deterministic checks over the memory. Runs no model. Scoped to the current model and prompt version unless `--all-versions` |
| `tr-ocrtext <in.pdf> <out.txt>` | Text layer that keeps Tesseract's per-word confidence and writes `OCR_ILLEGIBLE` below the floor. `tr-pdf` calls it instead of `pdftotext` |
| `tools/ocr-check.py <f.pdf> [--pages N] [--gate PCT] [--no-vision]` | Reads pages with Tesseract *and* a vision model and compares the numbers. Prints counts only, never document text. **Operator only** |
| `tools/phase1-setup.sh` | Prepares the Phase 1 comparison on a real subset; stops for OCR verification. **Operator only** |
| `case-guard-desktop [--check]` | The same refusal for the desktop app, which never consults `PATH`. Installed by `tools/install-desktop-guard.sh` |
| `tools/cycle-test.sh` | End-to-end run over the fixtures, no container needed |
| `tools/highlight-docx.py <f.docx> [--apply]` | Re-colours command blocks in the operating documents that lost their highlighting |

## Design invariants

Do not change these without discussing with the operator first.

1. **Filenames are preserved** from `source/` to `translated/`. This is a
   client requirement and the basis of `tr-status`. Optional `TR_SUFFIX`.
   The one exception is the extension: a scanned PDF cannot be regenerated
   as a PDF and plain text has no formatting to preserve, so both deliver a
   `.docx`. That mapping lives in `OUT_EXT` / `trlib.target_name()` and is
   mirrored by `out_ext_for()` in `bin/tr-run`. **Both must agree** — when
   they did not, `tr-run` wrote `x.docx` while `tr-status` looked for
   `x.pdf`, so every PDF reported as missing and its output as orphaned,
   permanently.
2. **The client drop is not a clean corpus, and its shape is preserved.**
   Files arrive as nested folder trees — often several separate drops — and
   that structure is carried through `source/` to `translated/` untouched;
   `tr-run` and `tr-status` already walk it at any depth. The tree also mixes
   languages. `tr-inventory` classifies every file and only the ones in
   `TR_SRC` are translated: a Croatian file pushed through an sl→en prompt
   wastes hours of inference *and* writes a cached wrong answer into
   `work/tm.sqlite` that is silently reused from then on. `tr-run` warns
   loudly when no inventory exists rather than assuming the drop is clean.
3. **Segment granularity is the sentence**, because that is the reviewer's
   unit of work and it makes the memory reusable across documents.
4. **Abbreviations must not split sentences.** `ABBREV` in `lib/trlib.py`
   holds the Slovene legal list (`št.` `čl.` `odst.` `d.o.o.` …). Adding
   entries is expected; removing them breaks review ergonomics.
   Slovene spaces its abbreviations as often as not, so `_SPACED_ABBR_RE`
   covers `d. o. o.`, `s. p.`, `t. i.`, `l. r.` — without it a company
   suffix split one sentence into four segments, three of them a single
   letter, each becoming a reviewer unit and a memory entry.
   **Open question:** a colon is a boundary, so `Datum: 5. 7. 2024` becomes
   `Datum:` plus the date — a six-character segment. Defensible for labels,
   wasteful as a unit of review. Left as it is because changing boundary
   behaviour affects every segment in the corpus and would need re-measuring.
5. **Non-translatables pass through verbatim** — case numbers, file numbers,
   statute short forms, identifiers. Patterns in `glossary/nontranslatable.txt`.
   **Dates, amounts and times are not in this class.** They are *converted*
   to the target locale, on the translator's instruction. Into English:
   `March 5, 2024`, `12,450.00`, `2:30 p.m.` Into Slovene: `5. marec 2024` —
   the day takes a period because it is an ordinal, the month is lowercase,
   and the parts are spaced — plus `12.450,00` and a 24-hour clock.
   Neither `5 March 2024` nor `5. Marec 2024` is correct in either language;
   both were in this file before the translator corrected them.
   The value never changes; only its spelling does. This is why `tr-lint`
   canonicalises months and clock times before comparing numbers — without
   that, every date in the corpus raised a NUM finding and buried the real
   ones. German is not English here: it keeps the 24-hour clock and writes
   `5. März 2024`, so verify that pair before extending to it.
   Two files hold the prompt — `prompts/translate.txt` (the seed `case-init`
   copies into `_shared/`) and `_DEFAULT_PROMPT` in `lib/trlib.py` (the
   fallback). **They must say the same thing**, and changing either means
   bumping `TR_PROMPT_VERSION` under invariant 7.
6. **A completed provision is an interpretation, not a translation.** Asked
   to translate a source that quotes a statute or treaty and stops short of
   the famous continuation, the model supplies the rest from memory —
   measured at 2 of 10 well-known provisions, both ECHR article 6. The
   addition reads perfectly and contains no number, glossary term or
   non-translatable fragment, so **no deterministic check can see it**, and
   no prompt tested has prevented it: four variants failed identically, and
   an explicit instruction against it made no difference.
   What is detectable is the *context* — `trlib.flagged()` marks any segment
   citing a statute or treaty, for word-by-word review. Asking the model to
   audit its own output against the source (`prompts/audit.txt`) caught 6/6
   real additions with 0/15 false positives at ~12 s a segment; gated on the
   citation flag that is roughly +2% on a run, against +400% ungated.
   Not yet wired into a tool: `tr-lint` runs no model (invariant 8), so an
   audit pass belongs elsewhere. The blind spot is a famous provision
   paraphrased without a citation marker.
7. **The memory is the resume state.** `work/tm.sqlite` keys on
   `sha256(direction, model, prompt_version, source)`. Changing the prompt
   must bump `TR_PROMPT_VERSION` or stale translations get reused.
8. **`tr-lint` runs no model.** It must stay deterministic and fast.
9. **Projects are isolated.** Each has its own `work/tm.sqlite`. Translation
   memory must never be shared across matters — different clients, different
   confidentiality obligations. Glossary layers (shared base + project
   overlay); memory does not.

## Testing

```bash
tr-fixtures fixtures/
tr-xlsx fixtures/dokazi-velika.xlsx --survey   # no project needed
python3 -c "import sys;sys.path.insert(0,'lib');import trlib;print(trlib.segment('Po čl. 211 odst. 2 KZ-1. Sodišče je odločilo.'))"
# expect two segments, not four
```

`tr-fixtures` also writes `fixtures/drop/` — a nested, two-drop,
mixed-language tree, which is what `tr-inventory` is developed against.
Point a throwaway project's `source/` at it and expect 3 Slovene, 2
Croatian/Serbian, 1 English, 1 Armenian, 1 undetermined:

`tr-inventory` reads the *active project*, so a throwaway root needs a project
inside it and an `.active` marker naming it — `TR_PROJECTS` alone resolves to
"no active project" and exits 2:

```bash
mkdir -p /tmp/tri/probe/source
cp -a fixtures/drop/. /tmp/tri/probe/source/
printf 'probe\n' > /tmp/tri/.active
TR_PROJECTS=/tmp/tri tr-inventory
```

`TR_PROJECTS` is also what lifts the container-mounted requirement, which is
why a throwaway root works at all outside the encrypted container.

Language detection lives in `lib/trlang.py` and is built from the hunspell
dictionaries `tr-setup` installs — so none of this runs until `tr-setup` has.
It was calibrated against UDHR text (a separate source from the dictionaries,
so the measurement is not circular) at 152/152 on 60-word samples, Slovene
recall 25/25, no false positives; and at 357/365 on 25-word samples with
three false positives.

`MIN_TOKENS` is **60**, the shorter of the two lengths measured at zero false
positives — not a value between the two runs, where nothing was measured.
Below it the detector abstains. The UDHR samples are not in the repository;
`tools/calibrate_lang.py` re-measures against any labelled sample set, and
should be run after any change to the scoring.

A mock model server is the right way to test the pipeline without waiting
on real inference — it also keeps iteration fast. See the handover document.
