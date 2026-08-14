# offline-legal-translation

An offline Slovene↔English legal translation pipeline. It produces draft
translations on one machine with no network egress, so a certifying
translator edits rather than translates from scratch — and so that client
material never leaves the premises.

Built for a real matter: a bundle of prosecution evidence, mostly scanned,
under a confidentiality obligation that made every cloud translation service
unusable. The constraints are what make it interesting.

## The constraint that shapes everything

Case material must never reach a network service, and it must never enter an
AI assistant session — including the assistant used to build this toolkit.
That is not a policy note, it is enforced:

- Client work lives in a **LUKS2 encrypted container**, mounted only while
  someone is working.
- `case-open` refuses to mount while a Claude Code process is running.
- A `PATH` wrapper refuses to launch Claude Code while the container is
  mounted, and a `.desktop` override does the same for the desktop
  application, which never consults `PATH`.
- `case-status` **reports whether each guard is actually installed** rather
  than asserting the boundary holds. That check exists because the desktop
  guard was once written, documented as closing the hole, and never
  installed — the boundary was open for days while every document said it
  was closed.

The mountpoint is `chattr +i` immutable while closed, so a tool run against
a closed container writes nothing to the bare directory instead of silently
producing plaintext where the encryption is not.

## What it does

```
tr-inventory          classify every file by source language
tr-inventory --count  OCR the scans, count source words, size the job
tr-ocrstat            per-file unreadable rate, against measured thresholds
ocr-check.py          read a page with two engines, compare the numbers
tr-run                translate what triage matched; resumable
tr-lint               deterministic checks; the reviewer's worklist
tr-terms              terms the model rendered two ways; glossary candidates
```

Inference is local, through [Ollama](https://ollama.com), against a Slovene
continual-pretrained Gemma (`GaMS3-12B`, Q8). Word documents, spreadsheets,
plain text and scanned PDFs each have a worker; filenames and the shape of
the client's folder tree are preserved into the deliverable.

## The parts worth reading

**OCR that says what it could not read.** Handwriting does not fail loudly —
Tesseract emits plausible words rather than nothing, and a model then
translates them fluently. `tr-ocrtext` keeps the per-word confidence and
replaces anything below the floor with `OCR_ILLEGIBLE`, turning a silent
fabrication into a visible instruction to go and read the page.

**Legibility is not correctness.** A confidence floor cannot catch
`12.450,00` misread as `1248000` — that scores 86% and reads as a fact all
the way to the deliverable. Only a second engine reading the same page finds
it, which is what `ocr-check.py` is for: Tesseract and a local vision model
(`deepseek-ocr:3b`, through the same Ollama instance — nothing leaves the
machine) read each page independently, and their number sets are compared.
It separates genuine disagreements from formatting differences, and
deliberately picks no winner — neither engine is authoritative, so a
disagreement is a page for a person to read, not a vote to settle. The
pipeline's text layer still comes from Tesseract, where the per-word
confidence lives; the second read exists to locate doubt, not to replace
it.

**Not everything is a scan.** A born-digital PDF already carries exact text;
rasterising and re-reading it can only introduce errors that were never in
the document. `tr-pdf` detects this and uses the text directly — while
treating a PDF carrying somebody else's OCR layer (`GlyphLessFont`) as a
scan worth re-reading.

**A translation memory that knows when it is stale.** Segments are keyed on
direction, model, prompt version *and the glossary terms that applied to
that segment* — so correcting one term retranslates the segments containing
it and leaves the rest cached. Deliverables record which model and prompt
produced them, because "output newer than source" answers whether a file was
edited, not whether it is still correct.

**Checks that run no model.** `tr-lint` catches what a language model is
structurally worst at noticing: a number present in the source and absent
from the target, a non-translatable altered, an agreed term not used, a
segment handed back untranslated. Seconds, no inference, and it produces a
worklist rather than a pass/fail.

**Documentation generated from the source.** The environment table, the
command reference and the tools list are written from `lib/registry.py` and
from the tools' own argparse definitions by `tools/gen-docs.py`, and a
pre-commit hook refuses a commit where they have drifted. Hand-maintained
tables had already gone stale in every way that allows.

## Measured, not assumed

The planning documents assumed 4 tokens/second. Reality was **0.81**, about
48 seconds per segment, most of it prefill that no amount of caching
avoids — a five-fold error that would have mispriced the work.

Cost tracks **segments, not words**. A spreadsheet is the worst possible
shape: 370 cells cost more than 2,255 words of prose, because each call pays
a near-fixed overhead regardless of length. Batching short segments cut that
by 4×; it does not help prose, where generation genuinely dominates.

Every threshold in the tooling — the OCR confidence floor, the vision gate,
the unreadable-rate bands — carries the measurement it came from and the
sample size, in the code, next to the number.

## Getting started

```bash
git clone <this repo> && cd offline-legal-translation
export KIT="$PWD" && export PATH="$KIT/bin:$PATH"
tr-setup          # packages, venv, dictionaries, git hooks
tr-model          # register the model with Ollama
tr-fixtures fixtures/      # synthetic Slovene documents to try it on
```

`tr-fixtures` generates invented legal text — a mixed-language nested drop
of the kind a client actually sends — so the pipeline can be exercised end
to end without any real material. `tools/cycle-test.sh` runs a full
container cycle against it.

The encrypted container is optional for trying the tools out: pointing
`TR_PROJECTS` somewhere other than the real container lifts the mount
requirement, deliberately and consistently across every tool.

## Layout

```
bin/         the commands
lib/         trlib.py (shared logic), guard.sh (the mount rule), registry.py
prompts/     the translation prompt, versioned; part of the cache key
glossary/    shared base terminology and non-translatable patterns
tools/       operator utilities, doc generation, test harnesses
docs-src/    prose that gen-docs.py assembles into the runbook
```

`CLAUDE.md` carries the design invariants — the nine rules that must not
change without discussion, each with the failure that produced it.

## Documentation

The operating manual, the step-by-step runbook and the design record live in
**offline-legal-translation-docs**. Start with the runbook if you want the
procedure; it is generated in part from these tools, so its command
reference cannot fall out of step with them.

## What this is not

A product. It is one language pair, one workflow, and one machine's measured
performance. The thresholds come from small samples and say so. German is
scaffolded but unverified. It is published because the constraints — offline
inference, a confidentiality boundary that has to be structural rather than
remembered, and OCR whose errors are fluent — produced decisions worth
reading, not because it generalises.

No client material is in this repository, or has ever been in its history.
