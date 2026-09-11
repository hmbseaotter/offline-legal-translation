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
| `tr-model` | Registers the Slovene↔English model with Ollama as `gams3:q8`. |
| `tr-model hf.co/mradermacher/EuroLLM-9B-Instruct-2512-GGUF:Q8_0 eurollm9b-2512:q8` | Only for English↔German matters: registers the model for that pair. About 10 GB. |
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

**For any pair other than Slovene→English, set it now.** `tr-project --new`
writes Slovene→English into the project's `project.conf`. For an
English→German matter, edit that file so these three lines read:

    TR_SRC=en
    TR_TGT=de
    TR_OCR_LANGS=eng

Nothing else is set. The model follows the pair — GaMS3 for
Slovene↔English, EuroLLM for English↔German — and `tr-run` refuses to start
when that model is not installed, instead of writing a failed translation
for every segment. Set the pair before step 3: triage keeps only the files
in `TR_SRC`, and counts only those toward the volume.

**German has variants.** `TR_TGT=de` is German as written in Germany, and
`de-DE` means the same. `TR_TGT=de-CH` drafts Swiss German by the Swiss
Federal Chancellery's rules: `12 450,00` with a non-breaking space,
`CHF 1250.50` and `Fr. 20.–` for money, `14.30`, and ss for ß — except in a
word the source has too, such as a name. `de-AT` is recognised — `tr-ref`
files references in it and `tr-terms --reference` reads them — but `tr-run`
refuses to draft into it until its conventions are settled. `TR_SRC` never
takes a variant; a Swiss German source is `de`.

**2. Copy the client's drop into `source/`, preserving its folder
structure.** Filenames and the shape of the tree are reproduced in
`translated/`, so the structure you create here is the structure you
deliver. Do not flatten it. Where two files in one folder would deliver
under one name — `x.docx` beside `x.pdf` — the one whose format changes
keeps its extension: `x.pdf` delivers as `x.pdf.docx`. Two names that differ
only in case are refused; rename one.

**Earlier translations, if the client has them.** Put both files of each
pair in the same folder anywhere under `reference/`, named alike apart from
a language suffix — `lease-2023_English.docx` beside
`lease-2023_German.pdf` — then:

    tr-ref

It lines the pairs up sentence by sentence, without a model, and `tr-run`
then takes the reference translation for any source sentence identical to
one it kept. Open `work/reference/pairs.tsv` before translating: every line
in it can reach a deliverable word for word. Numbers confirm the alignment,
and a sentence nothing confirms — no number of its own or either side — is
offered rather than reused, as `REF_OPTIONS [[…]] (unconfirmed)`: a
translation that omits, adds or swaps a sentence leaves the pairs around it
looking aligned. Where the references render a sentence more than one way,
the draft carries the choice instead of a model draft:

    REF_OPTIONS [[Der Mieter kann kündigen.]] | [[Der Mieter darf kündigen.]]

The rendering found in the most documents comes first, then the newest by
the date the file itself records, and a pinned glossary term puts the
rendering that uses it first. A translation read by OCR is offered the same
way, tagged `(OCR)`, and never reused on its own, and so is one rejoined at
a line-end hyphen that may have been the word's own, tagged `(hyphenation)`.
Search each deliverable for `REF_OPTIONS`, keep one rendering and delete the
rest; `tr-ref --conflicts` lists every rendering with its count and the date
that ordered it. A reference file replaced with a new version is read again;
one that cannot be read is listed, its sentences are dropped, and `tr-ref`
exits 1. References stay in this project; nothing reads another project's.

The suffix may be `_English`, `_German`, `_Slovene` or `_EN`, `_DE`, `_SL`,
in any case, and the two files may be different formats. It names a
language, not which side was the original, so the same pair serves
English→German and German→English work. A file with no suffix is listed
and skipped, never guessed.

German takes a variant after a hyphen — `_German-CH`, `_German-AT`, and
`_German` or `_German-DE` for Germany — so one original beside a Germany and
a Swiss translation makes two pairs. A German translation is reused only in
a project whose `TR_TGT` is its variant. One in another variant is never
reused; where the project's own variant has no reference for a sentence, it
is offered as `REF_OPTIONS [[…]] (de-CH)` — and, in a Swiss project, spelled
with ss.

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
rather than sampling, and has `tr-pdf` make the text layer of every PDF —
the same layer, made the same way, that translation will use — so the OCR
cost is paid once. It writes:

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
stop and get better copies. Exits non-zero if anything is in the stop band,
or if any text layer cannot be measured.

**A text layer made by an earlier `tr-inventory --with-ocr` cannot be
measured.** That version wrote the text with plain `pdftotext`, so nothing
in it is marked `OCR_ILLEGIBLE` — and `tr-pdf` reused it, so neither did the
translation. `tr-ocrstat` names those files, and any PDF with no text layer
yet, and exits non-zero. Step 4 reads each of them again, however unchanged
the PDF, keeping the old copy as `<name>.txt.unmarked` and never writing over
an earlier one — once `tesseract` and `pdftoppm` are installed; until then
nothing can mark the layer, and it is left as it is. A project already
translated from such layers was translated without unreadable words marked:
after step 4, `tr-run` drafts again every deliverable whose text layer
changed.

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

`tr-run` works from the **manifest**, not from a directory walk — so a file
added to `source/` after the last `tr-inventory` is invisible to it. Re-run
step 3 whenever you add anything. `tr-run` now names any file it finds on
disk that the manifest has never seen, rather than leaving it out silently.

Resumable at two levels: it skips a file whose deliverable is current, and
within a file every segment already in the memory is reused. Interrupting it
costs at most one segment. A deliverable is drafted again when anything that
made it has changed since it was written — the source, a PDF's text layer,
the glossary, the reference translations, the model, the prompt or the
kit's drafting code — and the `redo` line says which; `tr-status` lists the
same. A deliverable changed after `tr-run` wrote it, such as one a
translator corrected in place, is never overwritten: it is listed as
`kept`, and drafted again once it is moved aside.

A segment the model could not translate is written `[TRANSLATION FAILED]`,
and its file counts as failed: nothing is recorded for it, the next run drafts
it again, and `tr-run` exits 1 whenever a file failed.

**After updating the kit** nothing needs deleting. Run `tr-ref` where the
project has references and step 4 where it has PDFs, then `tr-run` and
`tr-lint`: every deliverable is drafted again once, from the memory, with
today's conversions applied to rows written before them.

**9. Get the reviewer's worklist.**

    tr-lint

No model, seconds. Reports numbers dropped or invented, non-translatables
altered, glossary terms not used, segments returned unchanged, and every
`[TRANSLATION FAILED]` in a deliverable. This is
what the translator works from, not the raw draft.

**10. Harvest terminology.**

    tr-terms --min-count 3 --pin-all

Writes `glossary/candidates.tsv` — terms the model rendered more than one
way, and frequent terms worth pinning before they drift. The translator
picks one rendering per line; the survivors go into `glossary/project.tsv`,
or `_shared/glossary/base.tsv` if they are general legal vocabulary that
should outlive this matter.

Where the project has reference translations, harvest from those before the
first `tr-run` — the candidates are then the translator's own renderings,
and pinning them steers every draft instead of correcting it afterwards:

    tr-terms --reference --pin-all

**11. Re-run.** A pinned term changes the glossary every deliverable
records, so `tr-run` drafts each file again, but only the segments
containing the term go back to the model — minutes, not hours:

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
| The prompt text | **Everything** translated for the pairs whose prompt changed |

So a prompt change belongs before a full run, not after. On a twenty-hour
corpus that is the difference between minutes and starting again.

---

## Part 2 — Command reference

Generated from the tools. If a flag is here it exists; if it exists it is
here.

