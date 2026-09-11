# Offline legal translation kit

Scripts that drive **local** language models through Ollama — `gams3:q8` for
EN↔SL, `eurollm9b-2512:q8` for EN↔DE — to produce draft translations of legal
documents.

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
    bin/  lib/  glossary/  prompts/  tools/  tests/  .githooks/
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
              reference/             earlier translations: name_English + name_German (tr-ref)
              work/  logs/  glossary/project.tsv
```

`source/` holds the client's folder structure exactly as delivered — several
separate drops, nested several levels — and `translated/` mirrors it. Nothing
flattens the tree.

## Tools
<!-- GENERATED:tools -->
| Command                                                                  | Purpose                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
|--------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `case-init` / `case-open` / `case-close` / `case-status`                 | Encrypted container                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `tr-project [--new] <name>`                                              | List, create, or switch the active project                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `tr-setup`                                                               | One-time provisioning. Idempotent.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `tr-model [hf-tag] [name]`                                               | Register a GGUF with Ollama. No arguments: GaMS3 as `gams3:q8`, for sl↔en. For en↔de: `tr-model hf.co/mradermacher/EuroLLM-9B-Instruct-2512-GGUF:Q8_0 eurollm9b-2512:q8`                                                                                                                                                                                                                                                                                                                                                                                                        |
| `tr-fixtures [dir]`                                                      | Generate synthetic test documents, including a mixed-language drop                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `tr-inventory [--rescan] [--no-ocr] [--limit N]`                         | Classify every file in `source/` by source language. Run this before anything else. Against a real drop it is **operator only** — it opens every client file; against the fixture drop it is the documented development path                                                                                                                                                                                                                                                                                                                                                    |
| `tr-inventory --count [--with-ocr]`                                      | Words and segments per file, to size the job before starting. Scanned PDFs need `--with-ocr`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `tr-status`                                                              | Diff `source/` against `translated/`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `tr-run [-n] [--all] [file]`                                             | Batch translate; resumable. Without `--all`, only what the inventory matched                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `tr-docx` / `tr-xlsx` / `tr-pdf` / `tr-txt`                              | Per-format workers. `tr-xlsx` also takes `.xlsm` / `.xltx` / `.xltm`, all delivered as `.xlsx` — the translation carries no macros and should not claim to                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `tr-lint [--tsv F] [--all-versions]`                                     | Deterministic checks over the memory. Runs no model. Scoped to the current model and prompt version unless `--all-versions`                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `tr-ocrtext <in.pdf> <out.txt>`                                          | Text layer that keeps Tesseract's per-word confidence and writes `OCR_ILLEGIBLE` below the floor. `tr-pdf` calls it instead of `pdftotext`                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `tools/ocr-check.py <f.pdf> [--pages N] [--gate PCT] [--no-vision]`      | Reads pages with Tesseract *and* a vision model and compares the numbers. Prints counts only, never document text. **Operator only**                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `tools/phase1-setup.sh`                                                  | Prepares the Phase 1 comparison on a real subset; stops for OCR verification. **Operator only**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `case-guard-desktop [--check]`                                           | The same refusal for the desktop app, which never consults `PATH`. Installed by `tools/install-desktop-guard.sh`                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `tools/cycle-test.sh`                                                    | End-to-end closed→open→closed cycle against a throwaway project, using synthetic fixtures. Needs the container, and refuses if one is already open rather than closing someone else's. **Operator only** — `case-open` blocks while any Claude session is running, so this cannot run in one                                                                                                                                                                                                                                                                                    |
| `tools/highlight-docx.py <f.docx> [--apply] [--strict]`                  | Re-colours command blocks in the operating documents that lost their highlighting. `--strict` also repaints blocks that merely differ from the rules, which is mostly churn against hand-tuned ones                                                                                                                                                                                                                                                                                                                                                                             |
| `tools/gen-docs.py [--apply]`                                            | Writes the tables in CLAUDE.md and the manual from lib/registry.py. Run by the pre-commit hook, which refuses a commit where they have drifted                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `tests/run [module] [-k pattern]`                                        | The regression tests: invented documents in a throwaway root and a mock in place of Ollama, so no model and no case material. Seconds. Run before every commit                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `tr-terms [--min-count N] [--top N] [--pin-all] [--write] [--reference]` | Finds source terms the model rendered more than one way and proposes glossary entries. Runs no model. `--pin-all` proposes frequent terms too, since consistent-and-wrong is one find-and-replace while inconsistent is a hunt through every variant. `--reference` harvests from the reference translations `tr-ref` lined up instead of from the drafts. **Operator only**                                                                                                                                                                                                    |
| `tr-ocrstat [--min-pct N]`                                               | Unreadable-token rate per PDF, worst first, against the 5%/20% thresholds. Answers "verify the OCR" for a whole corpus rather than one file. Legibility only — a misread digit in clean print scores high; use `ocr-check.py` for those. **Operator only**                                                                                                                                                                                                                                                                                                                      |
| `tr-ref [--rebuild] [--conflicts]`                                       | Lines up reference translations in the project's `reference/` — each pair in one folder, named alike apart from a language suffix (`_English`, `_German`, `_German-CH`) — sentence by sentence, without a model. `tr-run` then takes the translator's rendering for any identical source sentence, and a German one only where `TR_TGT` is its variant. Where renderings disagree the draft carries a `REF_OPTIONS` token listing them; `--conflicts` shows every rendering and the date that ordered it. Read `work/reference/pairs.tsv` before translating. **Operator only** |
<!-- /GENERATED:tools -->

## Environment

<!-- GENERATED:env -->
| Variable            | Default                                  | Purpose                                                                                                                                                                                                                                                                 |
|---------------------|------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| TR_PROJECTS         | ~/translation-work/confidential-projects | Container root holding all projects                                                                                                                                                                                                                                     |
| TR_ROOT             | (active project)                         | Override to target one project for a single command                                                                                                                                                                                                                     |
| TR_MODEL            | (by language pair)                       | Overrides the model chosen for the pair: gams3:q8 for sl↔en, eurollm9b-2512:q8 for en↔de, none for sl↔de. Set it in a project's project.conf, not in ~/.bashrc                                                                                                          |
| TR_SRC / TR_TGT     | sl / en                                  | Per-project, in project.conf. Any two of sl, en, de. TR_TGT may name a German variant: de-DE (the same as de); de-CH, drafted by the Swiss Federal Chancellery's rules; or de-AT, which tr-ref and tr-terms read but drafting refuses until its conventions are settled |
| TR_SUFFIX           | (empty)                                  | Per-project, in project.conf. Set if the client requires it                                                                                                                                                                                                             |
| TR_NUM_CTX          | 8192                                     | Context window. Lower if memory is tight                                                                                                                                                                                                                                |
| TR_PROMPT_VERSION   | (from the prompt text)                   | Override only. Derived per pair from the prompt text actually sent, so editing the prompt changes it; sl↔en is v6                                                                                                                                                       |
| TR_OCR_LANGS        | slv+eng                                  | Tesseract languages of the source documents: eng for an English drop, deu for German                                                                                                                                                                                    |
| TR_OLLAMA           | http://127.0.0.1:11434                   | Ollama endpoint                                                                                                                                                                                                                                                         |
| TR_DICTS            | /usr/share/hunspell                      | Where tr-inventory looks for the hunspell word lists it detects language with                                                                                                                                                                                           |
| TR_OCR_SAMPLE_LANGS | slv+hrv+eng                              | Tesseract languages for the detection sampling pass on scanned PDFs                                                                                                                                                                                                     |
| TR_VENV             | ~/.translate-venv                        | Python environment the scripts re-exec into. Set before tr-setup to put it elsewhere                                                                                                                                                                                    |
| TR_NO_REEXEC        | (unset)                                  | Set to 1 to stay on the system interpreter. Diagnostics only; imports will fail                                                                                                                                                                                         |
| CASE_IMG            | ~/.case/confidential.luks                | The LUKS container file. Read by case-init, case-open, case-status                                                                                                                                                                                                      |
| CASE_MAP            | casedata                                 | Device-mapper name while the container is unlocked                                                                                                                                                                                                                      |
| TR_VISION_MODEL     | deepseek-ocr:3b                          | Second OCR engine used by ocr-check.py. qwen3.6 is the fallback                                                                                                                                                                                                         |
| TR_VISION_PROMPT    | Extract the text in the image.           | Prompt for that model. It transcribes; it does not follow instructions                                                                                                                                                                                                  |
| TR_OCR_MIN_CONF     | 40                                       | Tesseract confidence floor in tr-ocrtext. Below it, a word is marked unreadable                                                                                                                                                                                         |
| TR_ILLEGIBLE_MARK   | OCR_ILLEGIBLE                            | What tr-ocrtext writes in place of a word it could not read                                                                                                                                                                                                             |
| CLAUDE_DESKTOP_BIN  | /usr/bin/claude-desktop                  | The real binary case-guard-desktop launches once it has checked the mount                                                                                                                                                                                               |
| CASE_MNT            | ~/translation-work/confidential-projects | Where the container mounts. Also what the claude guard checks                                                                                                                                                                                                           |
<!-- /GENERATED:env -->

## Design invariants

Do not change these without discussing with the operator first.

1. **Filenames are preserved** from `source/` to `translated/`. This is a
   client requirement and the basis of `tr-status`. Optional `TR_SUFFIX`.
   The one exception is the extension: a scanned PDF cannot be regenerated
   as a PDF and plain text has no formatting to preserve, so both deliver a
   `.docx`. That mapping lives in `OUT_EXT` / `trlib.target_name()`, and
   `bin/tr-run` calls it rather than restating it. It used to keep its own
   `out_ext_for()`, with a comment on each side reminding the other to stay
   equal — and when they drifted, `tr-run` wrote `x.docx` while `tr-status`
   looked for `x.pdf`, so every PDF reported as missing and its output as
   orphaned, permanently. A rule needing a comment to keep two copies in
   step is a rule living in the wrong number of places.
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
   `5. März 2024` — `localize()` converts en→de and en→de-CH, and no other
   German pair. Swiss German (`TR_TGT=de-CH`) follows the Swiss Federal
   Chancellery: `12 450,00` with a non-breaking space, a decimal point only
   beside a currency (`CHF 1250.50`, and `Fr. 20.–` for whole francs),
   `14.30`, and ss for ß except in a word the source has too.
   From English, a number such as `5.10`, `3.2` or `14.30` reads as well as
   a section, a clause or a time as it does as a decimal. It is converted
   only with a currency beside it or a thousands separator in it, and never
   after a reference word (`Section 5.10`, `Art. 3.2`, `§ 5.1`) or in a time
   (`at 10.30`, `14.30 Uhr`); `tr-lint` lists every one written as a
   decimal (DEC). Dates compare as one value however they are written —
   `5.3.2024`, `2024-03-05` and `March 5, 2024` alike — so a converted date
   is not a number the model added.
   One file holds the prompt: `prompts/translate.txt`, read from the kit by
   `trlib.build_prompt()`. A missing file is a loud refusal, not a silent
   fallback. Rules that differ by language sit in `{when TGT=de}` … `{end}`
   blocks (conditions on `SRC`, `TGT`, `VARIANT` or `PAIR`), so the rules
   every pair shares are written once and a Slovene→English call is not sent
   German rules it would pay for in prefill. Germany's rendered prompt must
   stay byte-identical when the Swiss rules change: an English→German memory
   keys on its hash.
   It was two — a `_DEFAULT_PROMPT` constant in `lib/trlib.py` as well, with
   a note here that they must agree. Nothing read the shipped file at all, so
   they were identical by luck, and the first edit to either would have made
   the shipped copy a lie about what the model is told.
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
   `sha256(direction, model, prompt_version, source)`, plus the glossary
   terms that applied. Model and version are both chosen per direction:
   `trlib.model_for()` routes the pair (`TR_MODEL` overrides), and
   `trlib.prompt_version()` is a hash of the prompt text that pair is
   actually sent, so any edit to the prompt changes it by itself. It was a
   string bumped by hand, and a forgotten bump reused stale translations.
   The two v6 texts still map to `v6`, so memory written under that name
   stays valid; `TR_PROMPT_VERSION` remains as an override.
8. **`tr-lint` runs no model.** It must stay deterministic and fast.
9. **Projects are isolated.** Each has its own `work/tm.sqlite`. Translation
   memory must never be shared across matters — different clients, different
   confidentiality obligations. Glossary layers (shared base + project
   overlay); memory does not. Reference translations are per project too:
   `tr-ref` reads only the active project's `reference/`, and a sentence it
   kept is reused only within that project.

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

`tests/run` runs the regression tests: invented documents in a throwaway
root under `$TMPDIR`, removed afterwards, and `tests/mock_ollama.py` in place
of the model, so they take seconds and read no case material. Run them
before every commit; `tests/run test_pins` runs one module and
`tests/run -k Retry` the tests whose names match. A fix for a defect comes
with a test that fails without it.
