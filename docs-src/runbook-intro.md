**Runbook — the procedure, step by step**

Everything below runs in a **plain terminal with no Claude Code session
open**. The guards enforce that: `case-open` refuses while Claude is
running, and Claude refuses while the container is mounted. That is
deliberate — case material must never enter an assistant session.

Part 1 is the order of operations. Part 2 is the reference for every command,
generated from the tools themselves so it cannot fall out of step with them.

---

## Part 1 — The procedure

### Once per machine

| | |
|---|---|
| `tr-setup` | Packages, Python environment, dictionaries, git hooks. Idempotent. |
| `tr-model` | Registers the translation model with Ollama as `gams3:q8`. |
| `case-init 40G` | Creates the encrypted container. Once, ever. Put the passphrase in your password manager and copy `~/.case/header.bak` onto a USB stick — a corrupted LUKS header loses the data even with the right passphrase. |
| `tools/install-desktop-guard.sh` | Routes the desktop launcher through the guard. The PATH wrapper only covers the terminal. |

The header backup only changes when a passphrase is added, changed or
removed. Writing data never touches it, so one copy stays valid until you
change the passphrase.

**Then check that the boundary is real:**

    case-status

It reports whether each guard is actually installed, not merely whether the
container is closed. Both must read `installed`. This matters because the
guard is what makes the boundary structural rather than remembered — but
installing it is itself remembered, and that is the part that has failed in
practice: the terminal guard was in place, the desktop guard was not, and
the desktop application opened with case material mounted. `case-status`
used to say "Safe to start Claude Code" throughout, because it was reporting
the mount and assuming the rest.

### Per matter

**1. Open the container and create the project.**

    case-open
    tr-project --new kranj-2024

**2. Copy the client's drop into `source/`, preserving its folder
structure.** Filenames and the shape of the tree are reproduced in
`translated/`, so the structure you create here is the structure you
deliver. Do not flatten it.

**3. Classify every file by source language.**

    tr-inventory

A drop is not a clean corpus. It arrives mixing Slovene with English,
Croatian/Serbian and whatever else, and pushing a Croatian file through an
sl→en prompt wastes the inference *and* caches a wrong answer that is reused
silently from then on.

Read `work/inventory/by-lang/unknown.txt`. Files not in the source language
are out of scope for work and for billing.

**Correcting a language, so it stays corrected.** Edit the `lang` column in
`work/inventory/manifest.tsv`, and set that row's `method` column to
`manual`. A row marked `manual` is never re-detected — every later run
refreshes its size, word count and segments but leaves the language alone.

Without the marker your correction still survives, but as a preference
rather than a decision: the next run that re-reads the file will notice the
detector disagrees and **ask** before changing anything. The recorded
language always wins by default, including when you answer nothing, because
the detector's alternative verdict is often `unknown` — which would drop the
file out of the translation set entirely.

`--rescan` re-examines every file but does not discard your corrections; it
proposes, like any other run. `--accept-revisions` takes the detector's
verdict everywhere without asking, which is for scripts, not for a drop you
have curated.

**4. OCR everything and count the words.**

    tr-inventory --count --with-ocr

This is the volume baseline the quote rests on. It reads every file in full
rather than sampling, OCRs the scans, and caches the text where `tr-pdf`
will find it, so the cost is paid once. It writes:

| File | What it is | Safe to send? |
|---|---|---|
| `work/inventory/manifest.tsv` | Every file, language, words, segments | **No** — paths carry party names |
| `work/inventory/summary.txt` | Counts only | Yes |

Two things about the numbers. Source words is the billing unit; segments
govern machine time, which is a different question. And **spreadsheets are
counted for words but not for time** — a sheet of cells has no sentences to
segment, so the "machine time" figure excludes them. On a corpus with
spreadsheets the real figure is much higher than the one printed; run
`tr-xlsx --survey` on each sheet for its unique-string count, which is what
actually governs the work there.

**Not every PDF is a scan.** A born-digital document — exported from a word
processor rather than photographed — already carries exact text, and `tr-pdf`
uses it directly rather than rasterising and re-reading it, which could only
introduce errors that were never in the document. It says so:
`born-digital: 412 words of real text, no OCR needed`.

A PDF carrying somebody else's OCR layer is *not* treated as born-digital.
Tesseract writes its invisible text in `GlyphLessFont`, so its presence means
the text is OCR of unknown quality, and the file is re-read here — where at
least the confidence of each word is recorded.

**5. Check whether the OCR is good enough to build on.**

    tr-ocrstat

Worst file first, with a verdict against measured thresholds: under 5% of
tokens unreadable proceed, 5–20% look at the marked pages first, 20% or more
stop and get better copies. Exits non-zero if anything is in the stop band.

**6. Read what it flags.** For every file in the `look` or `STOP` band, open
its text layer against the page images:

    less work/ocr/<name>.txt
    xdg-open work/ocr/<name>.ocr.pdf

The name is the source path with `/` replaced by `__`. What you are looking
for is what is marked `OCR_ILLEGIBLE`: if a hand-filled amount or a case
number sits inside one, that value has to come from a person.

**7. For pages whose numbers carry weight, read them twice.**

    tools/ocr-check.py source/<file>.pdf --pages 2

This is the step `tr-ocrstat` cannot do for you, and the distinction matters:
**`tr-ocrstat` measures legibility, `ocr-check.py` measures correctness.** A
confidence floor catches handwriting and damage. It cannot catch `12.450,00`
read as `1248000` — that scores 86% and reads as a fact all the way to the
deliverable. Only two engines disagreeing finds it. A file at 0% unreadable
is legible, not verified.

**8. Translate.**

    tr-run

Resumable at two levels: it skips files already delivered, and within a file
every segment already in the memory is reused. Interrupting it costs at most
one segment. It re-translates a file whose source is newer than its output,
or whose output was produced by a different model or a superseded prompt.

**9. Get the reviewer's worklist.**

    tr-lint

No model, seconds. Reports numbers dropped or invented, non-translatables
altered, glossary terms not used, and segments returned unchanged. This is
what the translator works from, not the raw draft.

**10. Harvest terminology.**

    tr-terms --min-count 3 --pin-all

Writes `glossary/candidates.tsv` — terms the model rendered more than one
way, and frequent terms worth pinning before they drift. The translator
picks one rendering per line; the survivors go into `glossary/project.tsv`,
or `_shared/glossary/base.tsv` if they are general legal vocabulary that
should outlive this matter.

**11. Re-run.** Pinning a term invalidates only the segments containing it,
so this is minutes, not hours:

    tr-run
    tr-lint

**12. Deliver from `translated/`, then close.**

    cd ~ && case-close

`cd` first, and not out of tidiness. A shell whose working directory is
inside the container keeps the filesystem busy exactly as an open file does,
so closing from within the project directory fails — and `-f` does not help,
because the kernel counts a working directory as a use of the mount.

Closing unmounts the container; it does not empty it. Everything stays
inside the container file, encrypted, and returns at the next `case-open`.
The corollary is retention: a finished matter occupies the container at full
size until someone opens it and deletes the project directory by hand. No
script removes client work.

### The order that matters

Two changes invalidate the translation memory very differently, and it
decides what you can afford to do when:

| Change | What re-runs |
|---|---|
| A glossary term | Only the segments containing that term |
| `TR_PROMPT_VERSION` | **Everything** |

So a prompt change belongs before a full run, not after. On a twenty-hour
corpus that is the difference between minutes and starting again.

---

## Part 2 — Command reference

Generated from the tools. If a flag is here it exists; if it exists it is
here.

