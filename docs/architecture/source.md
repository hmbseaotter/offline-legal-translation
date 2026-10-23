---
title: offline-legal-translation — Architecture and Workflow Report
short_title: offline-legal-translation
subtitle: An offline, confidentiality-enforcing pipeline that drafts legal translations with local language models
repo: https://github.com/hmbseaotter/offline-legal-translation
commit: aea0447
date: 2026-10-23
---

# Executive summary

`offline-legal-translation` is a command-line toolkit that produces **draft translations of legal documents entirely on one machine**: inference is configured for a local model server, so documents need not leave it. It translates Slovene↔English and English→German (including Swiss German). The drafts are not the end product: a certifying human translator edits them, so the toolkit's job is to turn "translate from scratch" into "review and correct".

It was built for a real criminal matter: a bundle of mostly scanned prosecution evidence under a confidentiality obligation. That obligation ruled out every cloud translation service and, unusually, also ruled out letting the case material into the AI coding assistant (Claude Code) that was used to *build* the toolkit.

The repository has three big ideas that a reader should take away:

1. **Confidentiality is enforced by mechanism, not by policy.** Case files live in an encrypted disk container. Small wrapper scripts make "container open" and "assistant running" mutually exclusive, and a status command checks that those guards are actually installed rather than assuming they are.
2. **Every step that can fail silently is made to fail visibly.** Scanned text the OCR engine could not read is replaced by a visible marker; numbers are checked across source and target; stale drafts are detected and redrafted; translator edits are never overwritten.
3. **Measurement over assumption.** Thresholds and timing figures in the code record the measurement and sample size behind them.

Technically, the toolkit is a set of Bash and Python commands (`bin/`), a shared Python library (`lib/trlib.py` and two smaller modules), a single versioned prompt file, glossary files, operator tools and a mock-based regression test suite. Inference runs through Ollama, a local model server, on two open-weight models chosen per language pair.

::: S-only
The rest of this report explains the problem, the repository layout, the architecture and its main components, the per-segment translation logic, the end-to-end operator workflow, how to run it, and a short assessment.
:::

::: M
The rest of this report explains the problem, the repository layout, the architecture, each component's purpose and inner workings, the per-segment translation logic and data model, the end-to-end operator and developer workflows, how to run it, an assessment of strengths and limits, and a glossary.
:::

# Context and problem

A law firm or translator receives a "drop" of client documents: Word files, spreadsheets, text files and, above all, scanned PDFs. The documents must be translated for court use. Three facts make this hard:

- **Confidentiality.** The material relates to a pending prosecution. Sending it to an online translation service, or to any AI assistant that processes text on remote servers, would breach the obligation.
- **Messy input.** The drop is a nested folder tree, often several drops, mixing languages (Slovene, English, Croatian/Serbian, Armenian and others). Most pages are scans, some with handwriting.
- **Cost of silent error.** A language model given a misread number or a garbled line produces a fluent, confident translation of the mistake. In legal documents that is the costliest error.

The toolkit answers these with local inference (Ollama on the same machine), an encrypted workspace with enforced separation from the assistant, triage before translation, OCR that marks what it could not read, deterministic checks that need no model, and careful caching so that corrections propagate.

::: M
## Why local models, and which ones

Inference uses Ollama, a program that serves open-weight language models over an HTTP API on `127.0.0.1` (the machine itself). The library's only network code talks to that local address. Two models are routed by language pair in `trlib.PAIR_MODELS`:

- **GaMS3-12B** (registered as `gams3:q8`, 8-bit quantized), a Gemma model continually pre-trained on Slovene and neighboring languages, for Slovene↔English.
- **EuroLLM-9B-Instruct-2512** (`eurollm9b-2512:q8`), which covers all EU official languages, for English→German (a German source is refused). GaMS3 never saw German in training, so it is deliberately not used there.

Slovene↔German has no model; the code refuses rather than pivoting through English, which would compound errors. `TR_MODEL` in a project's settings can override the routing.

## Why "measured, not assumed" matters here

The README reports that planning documents assumed 4 tokens per second while the author's machine measured 0.81, about 48 seconds per segment for GaMS3, most of it re-reading the system prompt ("prefill") on every call. By its account cost tracks the number of segments, not words: a spreadsheet of 370 short cells cost more than 2,255 words of prose. The measurements themselves are not in the repository. This finding drove the batching of short segments (Section on the core engine) and the job-sizing commands. The code records about 10.5 seconds per segment for EuroLLM but labels that figure an estimate because it came from short invented text.
:::

::: L
## What "draft" means in this project

A deliverable is a translated copy of each source file, with the same file name and folder location, delivered as Word or Excel. It is a draft in a precise sense: it contains visible markers wherever a human decision is required. `OCR_ILLEGIBLE` marks words the scanner could not read; `REF_OPTIONS [[…]] | [[…]]` offers alternative renderings drawn from earlier human translations; `[TRANSLATION FAILED]` marks a segment the model could not translate. The reviewer searches for these tokens. A separate worklist from `tr-lint` lists suspicious segments, such as a number that appears in the source but not the target. A pilot workflow (`tools/phase1-setup.sh`) exists to measure whether editing drafts is actually faster than translating from scratch, with a stop rule if it is not.

## How the project evolved

The git history (126 commits from 2026-08-01 to 2026-09-25) falls into two bursts of work with overlapping themes. Knowing them helps explain why the code comments read the way they do:

1. **Build-out (2026-08-01 to 08-04).** The first commit already contains the container scripts and the terminal guard; the desktop guard followed on 08-02. In these days the kit also gained language triage built on hunspell dictionaries, the OCR cross-check, `tr-terms`, generated documentation with the pre-commit drift check, and prompt versions v5 and v6 (both on 08-03): v5 stopped the model from deciding what was illegible, and v6 told it that a label or column heading is still a segment to translate. Many commits fix a defect found by using the previous one, or a latent one: "key the OCR cache on the path, not the basename" closed a gap where two exhibits with the same file name in different drops *would have* shared one text layer.
2. **Hardening and new capability (2026-09-10 and 09-11).** These commits add the test suite, EuroLLM routing for German, Swiss German drafting, reference translations and `tr-refimport`, and fix how numbers, retries, failures and stale deliverables are handled. Many of the tests cite findings of an audit dated 2026-09-10 (identifiers such as H-1, M-6, L-2), though not all do.

The license was added on 2026-09-19. The last commits (09-25) include functional fixes as well as runbook edits: `tr-pdf` stops requesting PDF/A, reads `project.conf`, and `tr-inventory` records why an OCR failed. The later move to a content-derived prompt version came from the risk of someone forgetting to bump a hand-numbered one.

The comments throughout the code are effectively a defect log: most non-obvious lines carry a paragraph saying what went wrong before they existed.
:::

# Repository map

The repository holds only toolkit code. The README states that no client material has ever been committed (the file names in the history agree), and a pre-commit hook blocks document formats.

| Path | What it is | Why it exists |
|---|---|---|
| `bin/` | 24 commands (Bash and Python) | The operator's interface: container, project, triage, OCR, translation, QA |
| `lib/trlib.py` | Shared core library (~2,800 lines) | One implementation of every rule: paths, guards, segmenting, locale conversion, memory, prompt, model client |
| `lib/trref.py` | Reference-translation alignment | Reuses earlier human translations without a model |
| `lib/trlang.py` | Language detection | Triage of mixed-language drops before translation |
| `lib/guard.sh`, `lib/conf.sh` | Shell halves of the mount rule and settings parser | Shell commands share the Python rules instead of restating them |
| `lib/registry.py` | Registry of commands and environment variables | Single source for generated documentation tables |
| `prompts/` | `translate.txt` (the translation prompt), `audit.txt` | The prompt is data, versioned by its own hash |
| `glossary/` | Base terminology, institution names, verbatim patterns | Seed and base layers for terminology control |
| `tools/` | Operator utilities, doc generator, test harnesses | OCR cross-check, container cycle test, calibration |
| `tests/` | Regression tests with a mock Ollama server | End-to-end checks in seconds, no model, no case data |
| `docs-src/` | Runbook prose | Assembled into the operating documentation |
| `CLAUDE.md` | Rules for the assistant; design invariants; generated tables | States the data boundary and nine invariants |
| `.claude/settings.json` | Assistant permission deny-list | A backstop to the boundary |
| `.githooks/` | `pre-commit`, `pre-push` | pre-commit blocks documents and doc drift; pre-push chains to a global push check |
| `INSTALL.md`, `README.md` | Install steps and overview | — |

::: M
The README points to a separate documentation repository (`offline-legal-translation-docs`) holding the operating manual, runbook and design record. It was not reviewed for this report; the runbook source in `docs-src/` and the extensive comments in the code cover the same ground.
:::

::: L
## The commands in `bin/`

| Group | Commands | Role |
|---|---|---|
| Container | `case-init`, `case-open`, `case-close`, `case-status` | Create, open, close and inspect the encrypted container |
| Guards | `case-guard`, `case-guard-desktop` | Refuse to start the assistant while the container is open |
| Setup | `tr-setup`, `tr-model`, `tr-hwsurvey`, `tr-fixtures` | Install packages, register models, survey hardware, make test documents |
| Project | `tr-project`, `tr-status` | Select or create the active project; compare source against deliverables |
| Triage | `tr-inventory` | Classify every file by language; count words and segments |
| OCR | `tr-pdf`, `tr-ocrtext`, `tr-ocrstat` | Make and measure text layers for PDFs |
| Translate | `tr-run`, `tr-docx`, `tr-xlsx`, `tr-txt` | Orchestrator plus one worker per format |
| References | `tr-ref`, `tr-refimport` | Align earlier human translations; import them from an archive |
| Quality | `tr-lint`, `tr-terms` | Deterministic checks; terminology consistency |

## Layout on disk at run time

Two separate branches of the file system are used, deliberately:

```
~/Claude_Stuff/cli_projects/translation-tools/   the kit (this repo); assistant may work here
~/translation-work/docs/                          reference manuals; no case content
~/translation-work/regular-projects/             other client work; also denied to the assistant
~/translation-work/confidential-projects/        mountpoint of the encrypted container
    .active                                       name of the active project
    _shared/glossary/base.tsv                     terminology reused across matters
    <project>/project.conf                        language pair and options
    <project>/source/  translated/  reference/    client drop, deliverables, earlier translations
    <project>/work/tm.sqlite, deliverables.tsv    memory and deliverable records
    <project>/work/ocr/  inventory/  tmp/         text layers, triage output, scratch
    <project>/glossary/project.tsv  logs/         matter terminology, run logs
```

`INSTALL.md` asks for the kit to sit outside `~/translation-work/` so the assistant is never started near the data. The guard code itself is narrower: it refuses working directories inside or above `confidential-projects/` only.
:::

# Architecture

The system has five layers. The figure below shows how they relate and where the confidentiality boundary sits.

![Overall architecture: the kit, the local inference and OCR tools, the encrypted container, and the guards that keep the assistant and the case data apart.](diagrams/architecture.dot)

1. **Boundary layer.** The LUKS2 encrypted container and the scripts that open and close it, plus the guards that keep the coding assistant and case data apart. The tools refuse to write project data while the container is closed, unless a test root is chosen deliberately.
2. **Orchestration layer.** The `bin/` commands. `tr-run` is the main orchestrator; others handle triage, OCR, references and QA. Shell commands source `lib/guard.sh` and `lib/conf.sh`; Python commands import `trlib`.
3. **Core library.** `lib/trlib.py` holds every shared rule, with `trref.py` (reference alignment) and `trlang.py` (language detection) beside it.
4. **Format workers.** `tr-docx`, `tr-xlsx`, `tr-txt` and `tr-pdf` read a source file, push its segments through the core, and write a deliverable in the right format.
5. **Local services.** Ollama for translation (and a vision model for OCR cross-checking); Tesseract, ocrmypdf and poppler utilities for OCR and PDF text.

::: M
## Architectural principles visible in the code

- **One implementation per rule.** File-naming (`target_name`), the mount test (`guard.sh` and `trlib.PROJECTS_OVERRIDDEN`), the settings parser (`conf.sh` and `trlib._load_project_conf`), number comparison (`trlib.compare_numbers`) and the prompt (`prompts/translate.txt`) each live in one place. Comments record the defects that occurred when they lived in two.
- **Refuse loudly rather than fall back silently.** Missing prompt file, unmounted container, unknown language pair, a prompt override without language blocks, a model not installed in Ollama: each stops the command with a message naming the fix.
- **Data stays inside the encryption.** Temporary files of OCR runs (rendered page images, ocrmypdf and Ghostscript scratch) are created inside the project's `work/tmp/`, never `/tmp`, because `/tmp` can reach unencrypted swap.
- **Derived versions, not hand-bumped ones.** The prompt version is a hash of the prompt text; the "drafting version" is a hash of the code files that shape a deliverable.
:::

# Components in detail

Each component is described by its purpose (what problem it solves) and how it works.

## Confidentiality boundary

**Purpose.** Keep case material encrypted when not in use, and make it impossible for the coding assistant to run while the material is reachable.

**How it works.** `case-init` creates a sparse 40 GB file, formats it as a LUKS2 encrypted volume with an ext4 file system, backs up the LUKS header, and makes the empty mountpoint immutable with `chattr +i`. Immutability means a tool run against a closed container cannot silently write plaintext into the bare directory. `case-open` unlocks and mounts the volume, but first refuses if any process named `claude` is running. In the other direction, `case-guard` is installed as `~/.local/sbin/claude`, earlier on `PATH` than the real launcher, and refuses to start the assistant while the container is mounted. `case-status` reports whether the container is open and **whether each guard is actually installed**.

::: M
### The mutual exclusion in detail

![Container states and the guards that enforce mutual exclusion between case data and assistant sessions.](diagrams/guards.dot)

The boundary has two halves, and the code comments stress that neither alone is enough: without both, the operator could simply do the two actions in the other order.

- **`case-open`** checks `pgrep -x claude`. If anything matches, it prints the process IDs and their parent process names, because the desktop app keeps a `claude` child process alive after a conversation is closed. Only then does it lift the immutable flag, run `cryptsetup luksOpen`, mount, and take ownership of the mountpoint.
- **`case-guard`** (the terminal wrapper) finds the real `claude` binary further down `PATH`, skipping itself, and runs three checks before handing over with `exec`: the container is not mounted (exit 3 otherwise); the data directory, if unmounted, contains no ordinary files, which would mean case material sitting unencrypted (exit 5); and the current directory is not inside or above the data directory, which could be mounted mid-session (exit 4).
- **`case-guard-desktop`** covers the desktop application, which is launched from a `.desktop` file and never consults `PATH`. `tools/install-desktop-guard.sh` writes a user-level copy of the system `.desktop` entry with every `Exec=` line rewritten to call the guard, including the right-click actions. On refusal it shows a dialog (kdialog or notify-send) since there is no terminal. A `--check` flag reports the decision without showing anything, so testing the guard does not look like a real alarm.
- **`case-close`** uses `lsof` to report what still holds the mount (telling a shell merely sitting in it, fixed by `cd ~`, from open files), then unmounts, closes the LUKS mapping and re-arms `chattr +i`.
- **`case-status`** checks that `~/.local/sbin/claude` exists and is what `command -v claude` resolves to, and that every `Exec=` line in the desktop override points to the guard. The README explains why: the desktop guard was once written and documented as closing the gap, but never installed, and the boundary stayed open for days.
:::

::: L
### Backstops

Two further layers are explicitly described as backstops, not controls:

- **`.claude/settings.json`** denies the assistant read, edit, write and grep access to both data trees (`confidential-projects/` and `regular-projects/`). It denies reading commands (`cat`, `head`, `tail`, `less`, `grep`, `rg`) when aimed at those trees, denies `pdftotext`, `tr-run`, `tr-pdf`, `tr-ocrtext`, `case-open`, `curl`, `scp` and `rsync` outright, and asks before `git push`. Its own comment explains why some commands that open documents (`tr-inventory`, `tr-docx`, `tr-xlsx`, `tr-txt`) are not denied: the documented development path runs them against synthetic fixtures, and against real data they refuse anyway because the container is closed during a session.
- **`.githooks/pre-commit`** refuses to commit any document format (`.docx`, `.pdf`, `.xlsx` and so on), anything under `fixtures/`, or any file over 1 MB, since the kit is small text files only. It then checks that generated documentation tables match `lib/registry.py`, using the staged files rather than the working tree. `tr-setup` points git at `.githooks` via `core.hooksPath`; both hooks chain to any global hooks the local setting would otherwise hide (`pre-push` does nothing else). `git commit --no-verify` bypasses the hook deliberately.

`CLAUDE.md`, which the assistant reads at session start, states the rule in a table of paths the assistant may and may not touch, including file *lists* such as the inventory manifest, because file names in a criminal matter carry party names and case numbers.
:::

## Project and settings

**Purpose.** Separate each client matter, and make every command agree on which matter and which language pair is in use.

**How it works.** Each matter is a directory inside the container. `tr-project --new <name>` scaffolds `source/`, `translated/`, `work/ocr/`, `logs/`, `glossary/`, `prompts/` and `reference/`, and writes the name to `.active`. Per-project options go in `project.conf` (for example `TR_SRC=en`, `TR_TGT=de-CH`, `TR_OCR_LANGS=eng+slv`, `TR_SUFFIX=auto`). Both the shell and Python halves parse this file as data rather than executing it, and an explicit environment variable wins over the file. Translation memory is never shared across projects (design invariant 9).

::: M
The mount rule is applied before any write. `trlib.require_root()` refuses when the target project lies under the default container path and the container is not mounted. The escape hatch for testing is to point `TR_PROJECTS` somewhere else. The code compares *resolved paths*, not whether the variable is set. `lib/guard.sh` applies the same resolved-path test for shell tools, but checks the mount only when `TR_ROOT` is not set explicitly; `require_root()` checks it either way.

Language settings are validated in one place. `TR_SRC` may be `sl` or `en` (a German source is refused because language detection has no German class). `TR_TGT` may be `sl`, `en`, `de`, `de-DE` (same as `de`), `de-CH` (Swiss rules) or `de-AT` (accepted for references, refused for drafting until its conventions are settled). A `TR_SUFFIX=auto` setting appends the target language label (for example `_German-CH`) to each deliverable, which makes every delivered translation usable later as half of a reference pair.
:::

## Triage: `tr-inventory` and language detection

**Purpose.** Decide which language each file is in, so that only files in the project's source language are translated. A Croatian file pushed through a Slovene→English prompt wastes hours *and* writes wrong answers into the memory that would be reused silently.

**How it works.** `tr-inventory` walks `source/` at any depth, extracts a sample of up to 400 words from each file (Word, spreadsheet, text, or PDF text layer; for a scan it OCRs two pages with a combined language set), and asks `trlang.detect()` for a verdict. Results go to `work/inventory/manifest.tsv` (every file, with path, language and confidence), `by-lang/*.txt`, and `summary.txt` (counts and the project name, no paths; the tool calls it safe to send to the client). `tr-run` then translates only manifest rows whose language matches `TR_SRC`, reports how many were held back, and warns about files on disk the manifest has never seen.

::: M
`trlang.py` is not a statistical n-gram model. It decides in four steps: script (Armenian and Cyrillic by Unicode block); discriminative vocabulary (how many words appear in one language's hunspell dictionary and in none of its rivals'); orthography (ć and đ count against Slovene); and abstention (fewer than 60 tokens, or a close score, gives "unknown" for a human to resolve). Croatian and Serbian are one class. The docstring records calibration against UDHR text: 152/152 correct on 60-word samples with no false positives, and the 60-token minimum is set at that measured point rather than between measured points.
:::

::: L
### What triage records and how an operator corrects it

Each manifest row records the file's path, extension, size, modification time, detected language, confidence, the extraction method (`docx`, `xlsx`, `text`, `pdf-text`, `pdf-ocr-sample`, `pdf-ocr-full`, `no-extractor` and so on), a note, and, after `--count`, words and segments. Files with no extractor (legacy `.doc`, images, archives, e-mail files) are recorded and counted, never guessed at. A resumed run reuses a row when the file's size and modification time are unchanged; `--rescan` forces a fresh look but still keeps hand-set languages. `--limit N` tries a large drop on its first N files without deleting the rest of the manifest. To fix a language by hand, the operator edits the row's `lang` and sets its `method` to `manual`; every later run keeps it. `summary.txt` reports the project name and counts by language but no paths; the tool's docstring calls it safe to send to the client as a sizing report.
:::

::: M
`tr-inventory --count` reads files in full and reports words *and* segments, since the translator is paid by words but machine time follows segments. `--with-ocr` makes the real text layer for every PDF by calling `tr-pdf --ocr-only`, so the OCR is done once and reused at translation time. A language set by hand (method `manual` in the manifest) is never overwritten, and when a later run disagrees with a recorded language it keeps the recorded one and reports the disagreement, unless `--accept-revisions` is given.
:::

## OCR stack

**Purpose.** Produce a text layer for each PDF that is faithful to the page and honest about what it could not read.

**How it works.** `tr-pdf` first checks whether a PDF is born-digital (at least 50 words of real text and no `GlyphLessFont`, the font Tesseract uses for invisible OCR text). If so, it uses that text directly, since re-reading it by OCR can only add errors. Otherwise it runs `ocrmypdf` (rotate, deskew, clean) and then `tr-ocrtext`, which re-runs Tesseract to get **per-word confidence** and replaces any word below a floor of 40 with the marker `OCR_ILLEGIBLE`. A handwritten line that is mostly unreadable becomes a single marker. The text layer is cached in `work/ocr/` and keyed by the file's path relative to `source/` plus a content hash, so a replaced PDF is read again.

::: M
Two further tools measure the result before any translation:

- **`tr-ocrstat`** counts the `OCR_ILLEGIBLE` rate per file and sorts worst first against thresholds of under 5% (proceed), 5–20% (look at the marked pages) and 20% or more (stop; rescan or request better copies). The docstring says these thresholds came from eight pages of two real documents and are starting points.
- **`tools/ocr-check.py`** addresses what a confidence floor cannot catch: a confidently misread digit in clean print (the documented example is `12.450,00` read as `1248000` at 86% confidence). It reads the same pages with Tesseract and with a local vision model (`deepseek-ocr:3b` through the same Ollama) and compares the sets of numbers each found. It separates formatting differences from real disagreements and deliberately picks no winner: a disagreement is a page for a person to read. It prints counts only, never document text, and writes transcriptions inside the container. By default it skips the slow vision pass on pages where Tesseract was confident (a 3% "gate"). It is an optional, manual tool: it reads the first two pages unless told otherwise, nothing in the pipeline consumes its result, and no setup script installs the vision model; it must be pulled into Ollama by hand.
:::

::: L
### Why `tr-pdf` is two-stage and why temporary files matter

`tr-pdf --ocr-only` stops after making the text layer and prints a reminder to verify names, dates, case numbers, amounts and diacritics against the page images before translating. The second stage hands the text layer to `tr-txt`, which writes a Word deliverable; a scanned PDF cannot be regenerated as a PDF, so its deliverable is `.docx`.

Every scratch file of an OCR run, including ocrmypdf's page images and Ghostscript's work files, is redirected into a per-run directory inside the container (`TMPDIR` set to `work/tmp/trpdf-…`) and removed on exit. The code explains why: `/tmp` on the target machine is RAM-backed, RAM can be swapped, and swap is unencrypted. A related comment explains that PDF/A output was dropped because Ubuntu's AppArmor profile for Ghostscript forbids its scratch files under the home directory, where the container lives.

Cached text layers made before confidence marking existed are detected (`trlib.ocr_layer_unmarked`) and set aside, never deleted, in case someone corrected them by hand; the file is then read again properly.
:::

## Core translation engine (`lib/trlib.py`)

**Purpose.** Turn a source segment into a target segment correctly, reproducibly and cheaply, and cache the result so a rerun costs nothing.

**How it works.** Text is split into sentence-sized **segments**, the reviewer's unit of work. Slovene legal abbreviations such as `št.`, `čl.`, `odst.` and `d. o. o.` do not end a sentence. Each segment then follows a fixed decision path (detailed in the next section): whole-segment dates, times and amounts are converted in code; untranslatable strings (case numbers and other patterns in `glossary/nontranslatable.txt`) pass through verbatim; a sentence found in a kept reference translation takes the human rendering; a sentence already in the **translation memory** is reused; only otherwise is the model called. Model replies are checked for truncation, implausible length and invented numbers, given one firmer retry if suspicious, then normalized (`finish_draft`) and stored.

::: M
### Prompt and prompt version

There is one prompt file, `prompts/translate.txt`, with shared rules (output only the translation, preserve meaning, keep identifiers verbatim, never alter a numeric value, pass `OCR_ILLEGIBLE` through unchanged) and language-specific blocks marked `{when TGT=de VARIANT=CH}` … `{end}`. `build_prompt()` selects the blocks for the pair, fills in language names, and appends a "Required terminology" block containing only glossary terms that occur in the segment, sorted so identical term sets produce byte-identical prompts. The **prompt version** is a hash of the text the pair is actually sent, so editing the German rules changes German versions only, and forgetting to bump a version is impossible. Two legacy hashes map to the old name `v6` so existing memory stays valid. A project or `_shared/prompts/translate.txt` may override the kit's prompt, but an override without `{when}` blocks is refused.

### Translation memory

`work/tm.sqlite` holds one row per translated segment. The key is a SHA-256 of the direction (for example `sl-en`), the model, the prompt version, **the glossary terms that applied to this segment**, and the source text. Including only the applicable terms means adding a banking term does not invalidate unrelated criminal-procedure segments, while correcting a term retranslates exactly the segments that contain it. When no glossary terms apply, the key is computed exactly as it was before terms were added to the key, so older rows remain reachable (a comment records that 532 rows were once orphaned by a changed separator). Rows are "finished again" when read (`refinish`), so a later fix to number formatting reaches work already done.

### Locale conversion and number safety

Dates, amounts and times are converted to the target convention, not copied: `5. 3. 2024` becomes `March 5, 2024` in English; `12,450.00` becomes `12.450,00` in Slovene and German; Swiss German writes `12 450,00`, `CHF 1250.50`, `Fr. 20.–` and times as `14.30` (the prompt asks for `14.30 Uhr` inside sentences), and uses ss for ß. A segment that is *only* such a value never reaches the model. Inside sentences, the model converts per the prompt and `fix_numeric_format()` corrects separators afterward. Conversions are conservative where meaning is ambiguous: an English `5.10` with no currency or percent could be a section number, so it is not converted, and an all-numeric `03/05/2024` is left alone because the month cannot be known. Number comparison (`compare_numbers`) folds dates and separators to canonical values first, so a correctly converted date is not reported as a changed number.

### Reply checks and retries

`ollama_translate()` sends one request with temperature 0.1 and a generation cap of the source length plus 64 tokens. A reply is suspicious if it was cut off by the cap, contains a line break the source lacked, is more than three times the source length plus 40 characters, or contains numbers the source does not have. A suspicious reply gets one retry prefixed "Translate only the text below. Reply with its translation and nothing else." Between the original and the retry, the reply whose numbers are closer to the source's wins. A second cut-off or over-long reply fails the segment; network errors and empty replies are retried up to three times. A reply whose only fault was added numbers is kept if the retry is no better (`tr-lint` then reports it). A failed segment is written as `[TRANSLATION FAILED] <source>`, and the worker exits non-zero so the file is redrafted next run.

### Batching short segments

Because every call pays a large fixed prefill cost, `ollama_translate_many()` groups up to 20 short, single-line segments (each at most 200 characters, 1,500 in total) into one numbered request. The reply must come back with exactly the same numbering, or the whole batch falls back to one call per segment; a silently misaligned batch would attach translations to the wrong cells. Lines flagged as suspicious go through the single-segment path individually. Each result is cached under its own key. The README reports a 4× saving on spreadsheets.
:::

::: L
### Institutions, citations and other details

- **First mention of institutions.** The translator wants an institution's source name in brackets beside its translation on its first mention in each document. `FirstMention` does this deterministically after translation, per document, using `glossary/institutions.tsv`. It is not done by the model because the memory is shared across documents and would cache the brackets.
- **Citation detector (unused).** `trlib.flagged()` can recognize segments citing a statute or treaty (Slovene markers such as `čl.`, `odst.`, `ZKP`, `KZ-1`, `EKČP`). Design invariant 6 in `CLAUDE.md` explains the motive: by the author's measurement the model completed well-known provisions from memory (2 of 10, both ECHR Article 6), which no deterministic check can see, and an audit prompt (`prompts/audit.txt`) caught 6 of 6 such additions with 0 of 15 false positives. `CLAUDE.md` says the flag "marks" such segments, but at this commit **no tool calls `flagged()` and none uses the audit prompt**.
- **Model routing and timing tables.** `PAIR_MODELS` routes by base language, so `de-CH` goes to EuroLLM. `SEC_PER_SEGMENT` holds 48.3 s for GaMS3 (measured, 12 samples) and 10.5 s for EuroLLM (labeled an estimate); an unmeasured model falls back to the slowest figure so estimates err long.
- **Venv re-execution.** Every Python entry point starts under the system interpreter; importing `trlib` re-executes the script under `~/.translate-venv`, where `python-docx` and `openpyxl` live.

### Locale conversion at a glance

The following examples are taken from the rules in the prompt file and the conversion functions in `trlib`:

| Value | Slovene | English | German (Germany) | Swiss German |
|---|---|---|---|---|
| Date | `5. marec 2024` | `March 5, 2024` | `5. März 2024` | `5. März 2024` |
| Amount | `12.450,00` | `12,450.00` | `12.450,00` | `12 450,00` (non-breaking space) |
| Money | — | — | — | `CHF 1250.50`, whole francs `Fr. 20.–` |
| Time | `14:30` (24-hour) | `2:30 p.m.` | `14:30` | `14.30` (`14.30 Uhr` in running text, per the prompt) |

Code converts sl→en, en→sl, en→de and en→de-CH. Other pairs are left alone on purpose, because applying another language's conventions silently would be worse than doing nothing. Swiss output also passes through `swiss_spelling()`, which writes ss for ß except in words where the source itself has ß (such as a German name). Non-breaking spaces hold digit groups together and keep `Fr.` with its amount, and a word joiner keeps the `–` of `Fr. 20.–` on the same line.

### Segmentation rules

`segment()` treats every newline as a hard boundary, then splits on sentence-ending punctuation (`.`, `!`, `?`, `:` and `;`) followed by space. A candidate break is ignored when the text before it ends with a listed abbreviation (`ABBREV`), a Roman numeral, a single capital initial, a numbered heading such as `3.2.`, or a spaced abbreviation such as `d. o. o.`. The code contains a 400-character test, but it never shortens a segment, so there is no effective length cap: a long run without sentence punctuation stays one segment. `CLAUDE.md` records one open question: the colon is a boundary, so `Datum: 5. 7. 2024` yields a six-character label segment. It was left as is because changing boundaries would change every segment, and therefore every memory key, in the corpus.
:::

## Format workers

**Purpose.** Preserve each document's structure and name while replacing its text.

**How it works.** `tr-run` chooses a worker by file extension. `tr-docx` walks body paragraphs, tables (including tables nested in cells), headers and footers, translates segment by segment, and writes each paragraph's text into its first run, keeping paragraph-level formatting but not mid-paragraph bold or italic. `tr-xlsx` collects each **distinct** cell string, translates it once (batched), and writes it back by lookup, so identical cells get identical translations; typed date cells get a target-locale number format. `tr-txt` (also used for OCR'd PDFs) segments plain text and writes a Word document, optionally bilingual with the source in grey italics.

::: M
Deliverable names come from one function, `trlib.target_names()`. The rule: same name and folder as the source; PDFs and text files become `.docx`; macro-enabled or template workbooks become `.xlsx` (the translation carries no macros and should not claim to); an optional `TR_SUFFIX` is inserted before the extension. If two sources in one folder would collide (for example `x.docx` beside `x.pdf`), the one whose format changes keeps its old extension too: `x.pdf.docx`. Names are compared case-insensitively because a folder copied to Windows would overwrite one with the other. `tr-xlsx --survey` reports how many distinct strings a workbook has and estimates machine time, without translating.
:::

## Reference translations

**Purpose.** Reuse sentences a certifying translator has already translated in earlier documents, without a model.

**How it works.** The operator places earlier translation pairs anywhere under the project's `reference/` folder, named alike apart from a language suffix (for example `lease-2023_English.docx` and `lease-2023_German.pdf`). `tr-refimport` can copy such pairs from an archive. `tr-ref` aligns each pair paragraph by paragraph and sentence by sentence by **length** (the Gale & Church method), using the numbers that both sides share as anchors. It keeps only one-to-one pairs whose numbers agree. During translation, a source sentence identical to a kept reference sentence takes the translator's rendering. Where references disagree, or a pair is unconfirmed by numbers, the draft instead carries `REF_OPTIONS [[…]] | [[…]]` for the translator to choose.

::: M
Alignment results are stored in `work/reference.sqlite`, with human-readable `work/reference/pairs.tsv` (what will be reused) and `rejected.tsv` (what was not, and why). The operator is told to read `pairs.tsv` before the first run. The rules err toward keeping less: a wrongly rejected pair costs one model call, while a wrongly kept pair puts the translation of a different sentence into a deliverable. A pair is "anchored" when both sides carry the same numbers and no sentence within three positions carries them too; pairs between two anchors may also be reused. A sentence with no anchor that still lines up one-to-one is offered as `REF_OPTIONS … (unconfirmed)` rather than reused. A rendering read by OCR, or rejoined at a line-end hyphen, is likewise only offered. German references are reused only for the exact variant the project targets. According to its docstring, `tests/test_references.py` sweeps omissions, insertions and swaps and fails if any wrong pair is kept.
:::

## Quality tools

**Purpose.** Give the reviewer a prioritized worklist and keep terminology consistent, without running a model.

**How it works.** `tr-lint` scans the translation memory and the deliverables and writes `work/lint-report.tsv`. Its checks, in priority order, are: `FAIL` (a failed segment), `NUM` (numbers missing or added, compared as values), `LONG` (target far longer than source), `NONTR` (a verbatim pattern altered), `DEC` (an English `5.10` written as a decimal `5,10`, which might be a section reference), `INCON` (one source translated two ways), `GLOSS` (agreed glossary term not used), `ECHO` (target identical to source) and `EMPTY`. `tr-terms` finds source terms the model rendered more than one way and proposes glossary entries; it writes them to `glossary/candidates.tsv` for the translator to choose from, or with `--write` appends them to the project glossary marked "unreviewed". `tr-status` compares `source/` against `translated/` and reports what is missing, current or stale.

::: M
`tr-terms` embodies a decision recorded in its docstring: an unconfirmed glossary is still worth having, because a term rendered *consistently* wrong is one find-and-replace, while a term rendered three ways requires a hunt. `--pin-all` therefore proposes entries for all frequent terms, not only inconsistent ones. `--reference` harvests terms from kept reference pairs instead of model drafts, which is better still because those renderings are human.

`tr-lint` reads the memory, and reads deliverables only for failure markers. Sentences reused from references and values converted in code never enter the memory, so `tr-lint` does not check them; the runbook says so.
:::

## Developer support

**Purpose.** Keep documentation truthful and the code safe to change without real data.

**How it works.** `lib/registry.py` lists every environment variable and command once. `tools/gen-docs.py` writes the tables in `CLAUDE.md` and the operating manual from it, and verifies that registry defaults match the values in the source. The pre-commit hook refuses commits where they have drifted. `tests/run` executes Python `unittest` modules in a throwaway project under `$TMPDIR`, with `tests/mock_ollama.py` answering model requests by rules. `tr-fixtures` generates invented Slovene legal documents and a nested mixed-language drop for development.

::: L
The test modules are organized by risk area, and most docstrings cite the audit finding they pin: `test_numbers.py` (43 tests on conversion and comparison), `test_references.py` (24, alignment and reuse), `test_staleness.py` (13, redrafting when inputs change), `test_names.py` (12, deliverable names and collisions), `test_ocr_layers.py`, `test_pairs.py`, `test_prompt_override.py`, `test_failures.py`, `test_temp_files.py` (OCR scratch stays inside the project), `test_conf.py`, `test_pins.py` (which pins the hashes that existing memory is keyed on, so a prompt change that would orphan memory fails loudly) and `test_refimport.py`. `tests/support.py` refuses to run under `~/translation-work` and points the Ollama URL at a closed port unless a test starts the mock, so no test can reach a real model by accident.

Other tools: `tools/cycle-test.sh` runs a full closed→open→closed container cycle with a throwaway project (operator only, since it needs the container); `tools/phase1-setup.sh` prepares the pilot comparison; `tools/calibrate_lang.py` re-measures language detection against any labeled sample set; `tools/highlight-docx.py` restores syntax coloring of command blocks in the Word manuals; `tr-hwsurvey` prints the hardware facts that decide which models can run.
:::

# How it works: logic and data model

## The life of one segment

Every worker sends segments through the same decision path in `trlib`. The order matters: cheaper, more trustworthy sources of a translation are tried before the model.

![Decision path for one source segment, from code conversion through reference reuse and memory lookup to a checked model call.](diagrams/segment-path.dot)

1. **Whole-value conversion.** If the segment is only a date, time or amount, `localize()` converts it in code. Deterministic and about 48 seconds cheaper than a model call.
2. **Verbatim check.** If it has no run of two letters, or fully matches a non-translatable pattern (for example a Slovene case number like `I K 12345/2024`), it is copied unchanged.
3. **Reference reuse.** If `tr-ref` kept this exact sentence, the translator's rendering (or a `REF_OPTIONS` choice) is used. These never enter the memory.
4. **Memory lookup.** If the memory has a row under the current key, it is reused after `refinish()`.
5. **Model call.** Otherwise the model is called, the reply checked, possibly retried, normalized and stored.
6. **Post-processing per document.** Word and text/PDF workers bracket first mentions of institutions (spreadsheets do not); the worker writes the text into the document.

## What makes a deliverable current

A deliverable is not "current" merely because it is newer than its source. `work/deliverables.tsv` records, for each source file, the hashes of the source and (for a PDF) its text layer, the glossary signature, a digest of the kept references, the model, the prompt version, a hash of the kit's drafting code, when it was written, and a hash of the written file. `trlib.deliverable_plan()` compares that record with the present state and assigns each file one action:

| Action | Meaning |
|---|---|
| `draft` | No deliverable yet |
| `current` | Nothing that made it has changed; skipped |
| `redo` | Something changed; the reason is printed. Unchanged segments still come from memory |
| `edited` | Inputs changed, but the file was edited after drafting; kept, never overwritten |
| `held` | The deliverable name holds another source's translation; redone |
| `clash` | Two sources would deliver under one name; refused |

::: M
This is why a run is resumable at two levels. Within a file, every segment already in memory is reused, so killing a run loses at most the request in flight: one segment, or one batch of up to 20 short segments. Across files, `deliverable_plan()` skips current files and redrafts only what a change touched. A worker that wrote any `[TRANSLATION FAILED]` exits with code 3; `tr-run` then removes the file's record so the next run treats it as a fresh draft rather than as a translator's edit.

## Data stores

| Store | Location | Contents |
|---|---|---|
| Translation memory | `work/tm.sqlite` | Table `tm(key, src, tgt, direction, model, prompt_version, ts)` |
| Deliverable records | `work/deliverables.tsv` | One row per source: path, output, hashes, model, prompt version, timestamps |
| Inventory | `work/inventory/` | `manifest.tsv` (path, ext, bytes, mtime, lang, confidence, method, note, words, segments), `by-lang/`, `summary.txt` |
| Text layers | `work/ocr/` | One `.txt` per PDF (path flattened with `__`), `.sha256`, OCR'd PDF |
| References | `work/reference.sqlite`, `work/reference/*.tsv` | Kept and rejected sentence pairs |
| Glossary | `_shared/glossary/base.tsv`, `<project>/glossary/project.tsv` | Tab-separated term pairs; project wins on conflict |
| Lint report | `work/lint-report.tsv` | Findings by check code |

All of these are inside the encrypted container. `deliverables.tsv` is rewritten through a `.tmp` file beside it and OCR scratch goes to `work/tmp/`, so no path-bearing scratch file lands on the unencrypted disk.
:::

::: L
## A worked example

Consider an invented Word paragraph in a Slovene→English project: *"Po čl. 211 odst. 2 KZ-1 je obdolženi plačal 12.450,00 EUR. Datum: 5. 3. 2024"*. (The first sentence echoes the segmentation test in `CLAUDE.md`; the glossary entry `obdolženi → the accused` is the seed example in `glossary/glossary.tsv`.)

1. `tr-docx` finds the paragraph and calls `segment()`. Because `čl.` and `odst.` are listed abbreviations, the first sentence is not split at them. The colon after `Datum` is a boundary, so three segments result: the sentence, `Datum:`, and `5. 3. 2024`.
2. `5. 3. 2024` is a whole-segment date, so `localize()` returns `March 5, 2024` without calling the model.
3. `Datum:` contains letters and is not a verbatim pattern. Assuming no reference or memory hit, it is sent to the model in its own call (`tr-docx` translates one segment per call; only `tr-txt` and `tr-xlsx` batch short segments).
4. The sentence is checked against references and memory. On a miss, `build_prompt()` adds a terminology block with `obdolženi -> the accused`, and the memory key includes that term. The reply is checked: if it contained a number not in the source, it would be retried once with the firmer prefix. `finish_draft()` then makes sure `12.450,00` appears as `12,450.00`.
5. The sentence cites `čl.` and `KZ-1`. `trlib.flagged()` would recognize that, but no tool calls it at this commit, so nothing marks the sentence for word-by-word review.
6. The three outputs are joined, any institution's first mention is bracketed, and the text is written into the paragraph's first run.
7. Later, `tr-lint` compares the numbers in source and target as values, after folding dates and separators to one spelling, and lists any number present on one side only as `NUM`.

If the translator later changes the glossary rendering of `obdolženi`, this sentence's memory key changes and it alone is retranslated on the next `tr-run`; the date and the label are untouched.

## Glossary layering

Two layers apply to term pairs at run time. The kit's `glossary/glossary.tsv` is only a seed, copied once into `_shared/glossary/base.tsv` when the container or first project is created; after that the shared copy is the curated one, and a project's `glossary/project.tsv` overrides it. For verbatim patterns and institution names, the kit's own file is always the base layer and the shared and project files only add to it, so a fix to a pattern in the kit reaches every matter. The prompt is deliberately not copied into `_shared` for the same reason: a copy would freeze the prompt at the day the container was created. For Swiss German targets, glossary renderings are passed through the Swiss spelling rule (ss for ß) before use.
:::

# Workflows

## Per-matter workflow (operator)

All steps run in a plain terminal with no assistant session; the guards enforce that. The runbook in `docs-src/runbook-intro.md` lays out twelve steps.

![End-to-end operator workflow for one matter, from opening the container to closing it.](diagrams/workflow.dot)

1. **Open and select.** `case-open`, then `tr-project --new <name>` or `tr-project <name>`.
2. **Configure.** Edit `project.conf`: language pair, OCR languages, deliverable suffix.
3. **Add sources.** Copy the client drop into `source/` with its folder tree intact.
4. **Add earlier translations (optional).** `tr-refimport`, `tr-ref`, read `work/reference/pairs.tsv`, then `tr-terms --reference --pin-all` (see step 10 for how terms are pinned).
5. **Classify.** `tr-inventory`; resolve anything in `by-lang/unknown.txt`.
6. **OCR and count.** `tr-inventory --count --with-ocr`; `summary.txt` sizes the job.
7. **Check OCR.** `tr-ocrstat` per file; `ocr-check.py` on doubtful pages. Stop if anything is in the stop band.
8. **Translate.** `tr-run -n` (dry run), then `tr-run`. Check `failed: 0`.
9. **Worklist.** `tr-lint` writes `work/lint-report.tsv`.
10. **Pin terms and redraft.** `tr-terms --min-count 3 --pin-all` writes `glossary/candidates.tsv`; the translator copies chosen renderings into `glossary/project.tsv` (or `--write` appends them, marked unreviewed). Then `tr-run` and `tr-lint` again; only segments with changed terms are redrafted.
11. **Deliver.** The translator edits `translated/`; `tr-status` confirms nothing is missing or stale; copy `source/` and `translated/` into the archive with `cp -av --update=none`.
12. **Close.** `cd ~ && case-close`.

::: M
### Inside `tr-run`

`tr-run` is a Bash script, but most decisions are delegated to `trlib` so there is one rule. In order it:

1. Resolves the project through `guard.sh` (refusing if the container is not mounted) and loads `project.conf`.
2. Validates the language pair and suffix in Python before listing any work.
3. Builds the file list from the manifest rows in `TR_SRC` (or every file with `--all`, or named files), and warns about files on disk the manifest has never seen.
4. Prints a banner (project, pair, model, prompt version, any override), checks that Ollama has the routed model, and asks for confirmation when interactive.
5. Gets the plan from `deliverable_plan()` and, for each file, skips, refuses, keeps, or runs the worker, logging to `logs/run-<timestamp>.log`.
6. Records or forgets each deliverable and exits 1 if any file failed.

### Resuming and changing things

A matter is rarely translated in one pass. The runbook's guidance: new files in `source/` mean returning to triage (step 5); new references to step 4; a changed glossary to step 8. In every case `tr-run` decides from the deliverable records what to redraft, and the translation memory ensures only segments actually affected cost model time.
:::

## One-time machine setup

`tr-setup` installs OCR, PDF and dictionary packages, creates the Python environment at `~/.translate-venv`, checks swap, and points git at the repository's hooks. `tr-model` registers GaMS3 with Ollama as `gams3:q8` (about 13 GB), and optionally EuroLLM as `eurollm9b-2512:q8` (about 10 GB), pinning context size and sampling settings in a Modelfile. `case-init 40G` creates the container. The terminal guard is copied to `~/.local/sbin/claude`, and `tools/install-desktop-guard.sh` installs the desktop guard. Finally, `case-status` must show both guards as `installed`.

::: M
## Development workflow (with the assistant)

Development happens in the kit directory, with the container closed, against synthetic data only:

1. `cd $KIT && claude` (the guard allows this only when the container is closed and the current directory is outside the data tree).
2. Generate fixtures with `tr-fixtures fixtures/` and point a throwaway project at them by setting `TR_PROJECTS` to a temporary root containing an `.active` marker.
3. Change code; add a test that fails without the fix (the stated rule for every defect fix).
4. Run `tests/run` (or one module, or `-k pattern`).
5. If a command or variable changed, edit `lib/registry.py` and run `tools/gen-docs.py --apply`.
6. Commit; the pre-commit hook blocks documents, large files and documentation drift.

If a real document is needed to reproduce a bug, `CLAUDE.md` says the operator hand-redacts an excerpt or reproduces the structure synthetically; the assistant does not ask for the original.
:::

::: L
## Pilot measurement (Phase 1)

`tools/phase1-setup.sh` prepares a controlled comparison on a real subset: three pages to be machine-drafted and three comparable but different pages to be translated from scratch. It runs pre-flight checks, triage, a word count, drafts only the machine set, lints it, writes bilingual review copies, and lays out a tally sheet (`tools/phase1-tally.tsv`). The question is the ratio of minutes per page editing a draft to minutes per page translating from scratch; at or above 1.0, the tooling does not help and the project stops. The script prints counts and paths, never document text.
:::

# Running it

The commands below are as documented in `README.md`, `INSTALL.md` and the runbook. They require Linux (the scripts use `apt`, `cryptsetup`, `chattr`, `mountpoint`), Ollama, and enough memory for a 12B model; the code mentions a 30 GB machine with added swap.

```bash
git clone <repo> "$KIT" && export PATH="$KIT/bin:$PATH"
tr-setup                     # packages, venv, dictionaries, git hooks
tr-model                     # register gams3:q8 with Ollama (once)
case-init 40G                # create the encrypted container (once)
cp bin/case-guard ~/.local/sbin/claude   # terminal guard
tools/install-desktop-guard.sh           # desktop guard
case-status                  # both guards must read "installed"
case-open && tr-project --new <matter>
tr-inventory && tr-inventory --count --with-ocr
tr-ocrstat
tr-run -n && tr-run
tr-lint && tr-terms --pin-all   # proposes terms in glossary/candidates.tsv
cd ~ && case-close
```

To try the pipeline without the container, set `TR_PROJECTS` to any other directory: that deliberately lifts the mount requirement across every tool. `tr-fixtures fixtures/` produces invented documents to translate, and `tests/run` runs the regression suite with a mock model once `tr-setup` has made the Python environment. Before first use, edit the user name in `.claude/settings.json`.

::: L
The main environment variables, taken from `lib/registry.py`, are in the appendix. The most important per-project settings are `TR_SRC`, `TR_TGT`, `TR_OCR_LANGS` (Tesseract languages, the bulk language first; the latest commit adds runbook guidance that this is the setting most likely to cause trouble) and `TR_SUFFIX`.
:::

# Assessment

## Strengths

- **A boundary that is structural and self-checking.** Mutual exclusion between the container and the assistant, immutable mountpoint, temporary files kept inside the encryption, and a status command that verifies the guards exist. The design learns from a documented failure rather than asserting safety.
- **Silent failure turned into visible work.** `OCR_ILLEGIBLE`, `REF_OPTIONS`, `[TRANSLATION FAILED]`, an optional two-engine number check, invented-number retries and a model-free lint worklist each target a way a fluent model hides errors.
- **Correct caching.** Memory keys include model, prompt hash and applicable glossary terms; deliverables record everything that made them; edits are never overwritten. Fixes reach work already done.
- **Disciplined engineering.** One implementation per rule, generated docs with a drift check, a mock-based test suite with tests tied to audit findings, and comments that record the defect behind each decision.

::: M
- **Honest about numbers.** Timing figures, OCR thresholds and detection accuracy carry sample sizes and are labeled as measured or estimated.
:::

## Limits and risks

- **Narrow scope by design.** Two language pairs, one machine's measured performance, one workflow. German sources and Slovene↔German are refused; Austrian German cannot be drafted. The README says plainly it is "not a product".
- **Small calibration samples.** OCR thresholds come from eight pages, the GaMS3 timing from 12 samples; English→German drafts had not yet been reviewed by a translator at the time of the latest commit.
- **Known blind spot.** The model can complete a famous legal provision from memory with no number or term to betray it. A citation detector and a measured audit prompt exist, but neither is wired into any tool.
- **Untranslated parts.** Word: mid-paragraph formatting is collapsed; footnotes, endnotes, comments and text boxes are skipped. Spreadsheets: formulas, sheet names, comments, headers and charts stay as they are.

::: M
- **Linux- and machine-specific.** Paths, the desktop entry name, `apt` packages and AppArmor notes assume one Ubuntu workstation; `.claude/settings.json` contains a hard-coded home path that must be edited per user.
- **Guards depend on process names and install locations.** `case-open` detects the assistant by a process literally named `claude`, and the terminal guard relies on `PATH` order. These are reasonable on a single-operator machine; in this reviewer's reading they guard against operator error rather than a determined user.
- **Egress is not blocked.** Inference is configured for Ollama on 127.0.0.1, but nothing in the kit blocks other network traffic; that is left to the machine, and setup itself downloads packages and models.
- **Large core module.** `trlib.py` is about 2,800 lines mixing configuration, guards, locale rules, memory and the model client. Thorough comments help, but the module is a lot to hold in one's head.
:::

::: L
- **Assistant permission rules are prefix patterns.** The settings file itself says they will not catch every spelling of a command; they are a backstop behind the container and guards.
- **Retention is manual.** Closing the container keeps all work; no script deletes a finished matter, which is safe for continuity but means retention obligations need a human step.
- **Separate documentation repository.** The operating manual lives in another repository; this report did not review it, so any divergence between it and the code is unassessed.

## Overall

For its stated purpose (offline draft translation of confidential legal material by one operator for one certifying translator) the repository is unusually careful. Its value as a reference lies less in the translation itself than in its patterns: enforcing a data boundary mechanically, versioning prompts by content, keying caches on everything that shapes an output, and making uncertainty visible to the human who has to sign off.
:::

::: M
# Glossary

- **Certifying translator.** The human translator who reviews drafts and certifies the final translation for court.
- **Drop.** A delivery of client documents, usually a nested folder tree.
- **LUKS2.** Linux Unified Key Setup, version 2: the standard Linux disk-encryption format. A LUKS container here is a single encrypted file mounted as a folder.
- **Mountpoint.** The folder where the decrypted container appears while open; empty when closed.
- **`chattr +i`.** A Linux file attribute making a directory immutable, so nothing can be written into it.
- **Ollama.** A local server that runs open-weight language models and answers HTTP requests on the same machine.
- **GaMS3, EuroLLM.** The two open-weight translation models used (Slovene↔English and English→German respectively).
- **Prefill.** The model's reading of the prompt before generating; here the dominant per-call cost.
- **OCR.** Optical character recognition; turning page images into text. Tesseract is the engine; ocrmypdf wraps it for PDFs.
- **Born-digital PDF.** A PDF exported from software, which already contains exact text.
- **`OCR_ILLEGIBLE`.** The marker written in place of words OCR could not read confidently.
- **Segment.** The unit of translation and review, normally one sentence.
- **Translation memory (TM).** The cache of previously translated segments, `work/tm.sqlite`.
- **Prompt version.** A hash of the prompt text sent for a language pair; part of the memory key.
- **Glossary.** Agreed source→target term renderings that the model is instructed to use.
- **Non-translatable.** A string pattern (case numbers, identifiers) copied verbatim.
- **Reference translation.** An earlier human translation used to supply sentences directly.
- **`REF_OPTIONS`.** A marker offering alternative human renderings for the translator to choose.
- **Triage / inventory.** Classifying files by language before translation.
- **Guard.** A wrapper script that refuses to launch the assistant while case data is reachable.
:::

::: L
# Appendix

## A. Environment variables (main entries from `lib/registry.py`)

| Variable | Default | Purpose |
|---|---|---|
| `TR_PROJECTS` | `~/translation-work/confidential-projects` | Container root; pointing elsewhere lifts the mount requirement |
| `TR_ROOT` | active project | Target one project for a single command |
| `TR_MODEL` | by language pair | Override the routed model; set per project |
| `TR_SRC` / `TR_TGT` | `sl` / `en` | Language pair, per project; `TR_TGT` may name `de-CH` |
| `TR_SUFFIX` | empty | Text added to deliverable names; `auto` = target language label |
| `TR_NUM_CTX` | 8192 | Model context window |
| `TR_BATCH_ITEMS` / `_CHARS` / `_ITEM_CHARS` | 20 / 1500 / 200 | Batching limits for short segments |
| `TR_PROMPT_VERSION` | from prompt text | Override only |
| `TR_OCR_LANGS` | `slv+eng` | Tesseract languages, bulk first |
| `TR_OCR_SAMPLE_LANGS` | `slv+hrv+eng` | Wider set for triage sampling of scans |
| `TR_OCR_MIN_CONF` | 40 | Confidence floor for `OCR_ILLEGIBLE` |
| `TR_ILLEGIBLE_MARK` | `OCR_ILLEGIBLE` | The marker text |
| `TR_VISION_MODEL` | `deepseek-ocr:3b` | Second OCR engine for `ocr-check.py` |
| `TR_OLLAMA` | `http://127.0.0.1:11434` | Ollama endpoint |
| `TR_DICTS` | `/usr/share/hunspell` | Dictionaries for language detection |
| `TR_VENV` | `~/.translate-venv` | Python environment |
| `TR_NO_REEXEC` | unset | Set to 1 to stay on the system interpreter (diagnostics only) |
| `TR_VISION_PROMPT` | `Extract the text in the image.` | Prompt for the OCR vision model |
| `CASE_IMG` / `CASE_MAP` / `CASE_MNT` | `~/.case/confidential.luks` / `casedata` / mountpoint | Container file, mapper name, mountpoint |
| `CLAUDE_DESKTOP_BIN` | `/usr/bin/claude-desktop` | Real desktop binary behind the desktop guard |

## B. `tr-lint` check codes

| Code | Finding |
|---|---|
| `FAIL` | `[TRANSLATION FAILED]` in a deliverable or the memory |
| `NUM` | A number present on one side only, compared as values |
| `LONG` | Target far longer than source: probable added text |
| `NONTR` | A verbatim pattern altered or dropped |
| `DEC` | English `5.10`-style number written as a decimal |
| `INCON` | One source segment translated two ways |
| `GLOSS` | Agreed glossary rendering not used |
| `ECHO` | Target identical to source |
| `EMPTY` | Empty target |

## C. The nine design invariants (from `CLAUDE.md`)

1. File names are preserved from `source/` to `translated/` (with defined extension and collision rules).
2. The client drop's folder shape is preserved, and only source-language files are translated.
3. The segment is the sentence.
4. Abbreviations must not split sentences.
5. Non-translatables pass through verbatim; dates, amounts and times are converted, never altered in value. One prompt file holds all rules.
6. A completed provision is an interpretation, not a translation; `CLAUDE.md` says citing segments are flagged, but at this commit no tool calls the detector.
7. The memory is the resume state, keyed on direction, model, derived prompt version and applicable terms; deliverables record everything that made them.
8. `tr-lint` runs no model.
9. Projects are isolated; memory and references never cross matters.

## D. Repository facts at the reviewed commit

- 126 commits between 2026-08-01 and 2026-09-25; head `aea0447`.
- About 13,900 lines across 67 tracked files; largest file `lib/trlib.py` (~2,775 lines), then `lib/trref.py` (~917) and `bin/tr-inventory` (~661).
- License: MIT.

## E. Operator tools in `tools/`

| Tool | What it does | Who runs it |
|---|---|---|
| `ocr-check.py` | Reads pages with Tesseract and a vision model; compares numbers; prints counts only | Operator, container open |
| `phase1-setup.sh` | Prepares the edit-versus-scratch pilot on a real subset | Operator |
| `phase1-tally.tsv` | Tally sheet for the pilot timings | Operator |
| `cycle-test.sh` | Full container open/close cycle with a throwaway synthetic project | Operator (assistant must not be running) |
| `install-desktop-guard.sh` | Writes the `.desktop` override routing the desktop app through its guard | Once per machine |
| `gen-docs.py` | Writes or checks the generated tables in `CLAUDE.md` and the manual | Developer; pre-commit hook |
| `calibrate_lang.py` | Measures language-detection accuracy at given sample lengths | Developer, after any scoring change |
| `highlight-docx.py` | Restores color coding of command blocks in the Word manuals | Documentation maintainer |
:::
