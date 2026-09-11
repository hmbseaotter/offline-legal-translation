**Runbook — the procedure, step by step**

Everything below runs in a **plain terminal with no Claude Code session
open**. The guards enforce that: `case-open` refuses while Claude is
running, and Claude refuses while the container is mounted. That is
deliberate — case material must never enter an assistant session.

Part 1 is the order of operations. Each step gives what to type and what to
check; the notes under it say why. Part 2 is the reference for every
command, generated from the tools themselves so it cannot fall out of step
with them.

---

## Part 1 — The procedure

### At a glance

| Step | Type | Check |
|---|---|---|
| Once per machine | `tr-setup`, `tr-model`, `case-init 40G` | `case-status` shows both guards `installed` |
| 1. Open the container, start or resume a project | `case-open`, then `tr-project --new <name>` or `tr-project <name>` | the project `tr-project` marks active |
| 2. Configure the project | edit `project.conf` | the pair, OCR languages and `TR_SUFFIX`, before the first run |
| 3. Add the sources | `cp -a <drop>/. source/` | the folder tree as received |
| 4. Add earlier translations | `tr-refimport`, `tr-ref`, `tr-terms --reference --pin-all` | `work/reference/pairs.tsv` |
| 5. Classify the files | `tr-inventory` | `work/inventory/by-lang/unknown.txt` |
| 6. OCR and count | `tr-inventory --count --with-ocr` | `work/inventory/summary.txt` |
| 7. Check the OCR | `tr-ocrstat`, `ocr-check.py` | nothing in the stop band |
| 8. Translate | `tr-run -n`, `tr-run` | `failed: 0` |
| 9. Get the worklist | `tr-lint` | `work/lint-report.tsv` |
| 10. Pin terms, draft again | `tr-terms --min-count 3 --pin-all`, `tr-run`, `tr-lint` | `glossary/project.tsv` |
| 11. Deliver into the archive | `cp -av --update=none` into its `in/` and `out/` | every file named or already there |
| 12. Close | `cd ~ && case-close` | |

**Resuming a project:** step 1, then the step the change calls for — new
files in `source/` go back to step 5, new references to step 4, and a
changed glossary to step 8.

### Once per machine

| | |
|---|---|
| `tr-setup` | Packages, Python environment, dictionaries, git hooks. Idempotent. |
| `tr-model` | Registers the Slovene↔English model with Ollama as `gams3:q8`. |
| `tr-model hf.co/mradermacher/EuroLLM-9B-Instruct-2512-GGUF:Q8_0 eurollm9b-2512:q8` | Only for English↔German matters: registers the model for that pair. About 10 GB. |
| `case-init 40G` | Creates the encrypted container. Once, ever. Put the passphrase in your password manager and copy `~/.case/header.bak` onto a USB stick — a corrupted LUKS header loses the data even with the right passphrase. |
| `tools/install-desktop-guard.sh` | Routes the desktop launcher through the guard. The PATH wrapper only covers the terminal. |

Then check that the boundary is real:

    case-status

Both guards must read `installed`.

Notes

- `case-status` reports whether each guard is actually installed, not merely
  whether the container is closed. The guard makes the boundary structural
  rather than remembered, but installing it is itself remembered, and that
  has failed in practice: the terminal guard was in place, the desktop guard
  was not, and the desktop application opened with case material mounted.
- The header backup only changes when a passphrase is added, changed or
  removed. Writing data never touches it, so one copy stays valid until you
  change the passphrase.

### Per matter

#### 1. Open the container, then start or resume the project

A new matter:

    case-open
    tr-project --new kranj-2024
    cd ~/translation-work/confidential-projects/kranj-2024

A matter already under way:

    case-open
    tr-project                  # the active project, and every project with its file counts
    tr-project kranj-2024        # switch to it
    cd ~/translation-work/confidential-projects/kranj-2024
    tr-status                   # what is done, missing or out of date

Every later step runs from the project folder.

Notes

- The active project is recorded inside the container, not in your shell,
  so it holds across terminals and is unset whenever the container closes.
  Every tool refuses to run when no project is set.
- `tr-project --none` clears the active project, and
  `TR_ROOT=<project folder> tr-status` works on another project once,
  without switching.

#### 2. Configure the project

Open the project's settings:

    nano project.conf

and set, before the first `tr-run`:

| Lines | For |
|---|---|
| `TR_SRC=sl`, `TR_TGT=en`, `TR_OCR_LANGS=slv+eng` | Slovene→English — what `tr-project --new` writes |
| `TR_SRC=en`, `TR_TGT=de`, `TR_OCR_LANGS=eng` | English→German; `TR_TGT=de-CH` for Swiss German |
| `TR_SUFFIX=auto` | Optional: each translation takes its language's label, `lease_German.docx` |

Notes

- Set the pair before step 5: triage keeps only the files in `TR_SRC`, and
  counts only those toward the volume.
- Decide the suffix before the first run as well. Changing it later gives
  every deliverable a new name: `tr-status` then lists each source as missing
  and its old translation as orphaned, and `tr-run` drafts them again under
  the new name, from the memory, leaving the old files in `translated/` to
  be removed by hand.
- `TR_SUFFIX=auto` spells the label as `tr-ref` reads it — `_English`,
  `_German`, `_German-CH` — so a translation filed beside its source cannot
  overwrite it, and is already half of a reference pair. A suffix naming
  another language than `TR_TGT` is refused; one naming none, such as
  `_translated`, is used as written.
- Nothing else needs setting. The model follows the pair — GaMS3 for
  Slovene↔English, EuroLLM for English↔German — and `tr-run` refuses to start
  when that model is not installed, instead of writing a failed translation
  for every segment.
- German has variants. `TR_TGT=de` is German as written in Germany, and
  `de-DE` means the same. `TR_TGT=de-CH` drafts Swiss German by the Swiss
  Federal Chancellery's rules: `12 450,00` with a non-breaking space,
  `CHF 1250.50` and `Fr. 20.–` for money, `14.30`, and ss for ß — except in a
  word the source has too, such as a name. `de-AT` is recognised — `tr-ref`
  files references in it and `tr-terms --reference` reads them — but
  `tr-run` refuses to draft into it until its conventions are settled.
- `TR_SRC` is `sl` or `en`: a German source is refused for now, because
  triage cannot detect German and German→English has no rules of its own.

#### 3. Add the sources

Copy the client's drop — or this matter's folder in the archive's `in/` —
into `source/`, keeping its folders:

    cp -a <drop>/. source/

Check that the tree under `source/` is the tree you received.

Notes

- Filenames and the shape of the tree are reproduced in `translated/`, so
  the structure you create here is the structure you deliver. Do not
  flatten it.
- Where two files in one folder would deliver under one name — `x.docx`
  beside `x.pdf` — the one whose format changes keeps its extension: `x.pdf`
  delivers as `x.pdf.docx`. Two names that differ only in case are refused;
  rename one.
- A file added later needs step 5 again: `tr-run` works from the inventory.

#### 4. Add earlier translations, if there are any

**a. From a past project kept in an archive.** List what would be copied,
read the list, then copy:

    tr-refimport <client>/in/356 <client>/out/356 --from en --to de
    tr-refimport <client>/in/356 <client>/out/356 --from en --to de --apply

The first folder holds the originals and the second the translations, each
read with its subfolders, and the copies land side by side in
`reference/356/`, named after the originals' folder. Before `--apply`, deal
with what the list says it will not copy: a translation without a language
label needs one in its name — `lease_German.docx` — in your copy of the
archive. A `.doc` or `.odt` file is copied but cannot be read: save it as
`.docx`, `.pdf` or `.txt`.

**b. Or by hand.** Put both files of each pair in one folder under
`reference/`, named alike apart from a language suffix:
`lease-2023_English.docx` beside `lease-2023_German.pdf`.

**c. Line the pairs up:**

    tr-ref

**d. Read `work/reference/pairs.tsv`.** Every line marked `yes` or `option`
reaches a deliverable in the words it shows, and no other line does.

**e. Pin the translator's terms, before the first run:**

    tr-terms --reference --pin-all

Pick one rendering per line in `glossary/candidates.tsv`, and put the
survivors in `glossary/project.tsv`.

Notes

- Copy only reviewed translations: `tr-ref` reuses their sentences word for
  word, and `tr-lint` never checks them.
- The suffix may be `_English`, `_German`, `_Slovene` or `_EN`, `_DE`,
  `_SL`, in any case, before every extension — `lease_German.pdf.docx` — and
  the two files of a pair may be different formats. It names a language, not
  which side was the original. A file with no suffix is listed and skipped,
  never guessed.
- `tr-refimport` gives an original without a label the `--from` label and
  keeps a file already labelled in its folder's language. It does not copy a
  translation without a label, a label naming another language, a name two
  files would share, or a file already there; it refuses overlapping
  folders, writes only inside the container, and leaves the archive as it
  was.
- German takes a variant after a hyphen — `_German-CH`, `_German-AT`, and
  `_German` or `_German-DE` for Germany — so one original beside a Germany
  and a Swiss translation makes two pairs. A German translation is reused
  only in a project whose `TR_TGT` is its variant. One in another variant is
  never reused; where the project's own variant has no reference for a
  sentence, it is offered as `REF_OPTIONS [[…]] (de-CH)`, and in a Swiss
  project written as a Swiss draft would be.
- `tr-ref` lines the pairs up sentence by sentence without a model, and
  `tr-run` takes the reference translation for any identical source
  sentence. Numbers confirm the alignment: a sentence nothing confirms — no
  number of its own or either side — is offered rather than reused, as
  `REF_OPTIONS [[…]] (unconfirmed)`, because a translation that omits, adds
  or swaps a sentence leaves the pairs around it looking aligned.
- Where the references render a sentence more than one way, the draft
  carries the choice:
  `REF_OPTIONS [[Der Mieter kann kündigen.]] | [[Der Mieter darf kündigen.]]`.
  The rendering found in the most documents comes first, then the newest by
  the date the file itself records, and a pinned glossary term puts the
  rendering that uses it first. A translation read by OCR is offered the same
  way, tagged `(OCR)`, and never reused on its own, and so is one rejoined at
  a line-end hyphen that may have been the word's own, tagged
  `(hyphenation)`. `tr-ref --conflicts` lists every rendering with its count
  and the date that ordered it.
- A reference file replaced with a new version is read again; one that
  cannot be read is listed, its sentences are dropped, and `tr-ref` exits 1.
  References stay in this project; nothing reads another project's.

#### 5. Classify every file by language

    tr-inventory

Read `work/inventory/by-lang/unknown.txt`. Files not in the source language
are out of scope for work and for billing.

To correct a language so that it stays corrected, edit the `lang` column in
`work/inventory/manifest.tsv` and set that row's `method` column to
`manual`.

Notes

- A drop arrives mixing Slovene with English, Croatian/Serbian and whatever
  else, and pushing a Croatian file through an sl→en prompt wastes the
  inference *and* caches a wrong answer that is reused silently from then on.
- A row marked `manual` is never re-detected: every later run refreshes its
  size, word count and segments but leaves the language alone. Without the
  marker a correction still survives, but as a preference rather than a
  decision: a later run that re-reads the file and disagrees **asks** before
  changing anything, and the recorded language wins by default, including
  when you answer nothing — the detector's alternative is often `unknown`,
  which would drop the file out of the translation set.
- `--rescan` re-examines every file but keeps your corrections; it proposes,
  like any other run. `--accept-revisions` takes the detector's verdict
  everywhere without asking, which is for scripts, not for a drop you have
  curated.

#### 6. OCR every PDF and count the words

    tr-inventory --count --with-ocr

Read `work/inventory/summary.txt`: counts only, and safe to send.
`work/inventory/manifest.tsv` is **not** — its paths carry party names.

Notes

- This is the volume baseline the quote rests on. It reads every file in
  full rather than sampling, and has `tr-pdf` make the text layer of every
  PDF — the same layer, made the same way, that translation will use — so
  the OCR cost is paid once.
- Source words are the billing unit; segments govern machine time.
  **Spreadsheets are counted for words but not for time** — a sheet of cells
  has no sentences to segment — so on a corpus with spreadsheets the real
  time is much higher than the figure printed. `tr-xlsx --survey` on each
  sheet gives its unique-string count, which is what governs the work there.
- A born-digital PDF — exported from a word processor rather than
  photographed — already carries exact text, and `tr-pdf` uses it directly
  rather than rasterising and re-reading it: `born-digital: 412 words of real
  text, no OCR needed`. A PDF carrying somebody else's OCR layer is *not*
  treated as born-digital: Tesseract writes its invisible text in
  `GlyphLessFont`, so the text is OCR of unknown quality, and the file is
  read again here, where at least the confidence of each word is recorded.

#### 7. Check the OCR

    tr-ocrstat

For every file in the `look` or `STOP` band, open its text layer against the
page images. The name is the source path with `/` replaced by `__`:

    less work/ocr/<name>.txt
    xdg-open work/ocr/<name>.ocr.pdf

For pages whose numbers carry weight, have them read twice:

    $KIT/tools/ocr-check.py source/<file>.pdf --pages 2

Check that nothing is in the stop band, and that no hand-filled amount or
case number sits inside an `OCR_ILLEGIBLE`: such a value has to come from a
person.

Notes

- `tr-ocrstat` lists the files worst first, against measured thresholds:
  under 5% of tokens unreadable, proceed; 5–20%, look at the marked pages
  first; 20% or more, stop and get better copies. It exits non-zero if
  anything is in the stop band, or if any text layer cannot be measured.
- **`tr-ocrstat` measures legibility, `ocr-check.py` measures correctness.**
  A confidence floor catches handwriting and damage. It cannot catch
  `12.450,00` read as `1248000` — that scores 86% and reads as a fact all the
  way to the deliverable. Only two engines disagreeing finds it. A file at 0%
  unreadable is legible, not verified.
- A text layer made by an earlier `tr-inventory --with-ocr` cannot be
  measured: that version wrote the text with plain `pdftotext`, so nothing
  in it is marked `OCR_ILLEGIBLE`, and `tr-pdf` reused it, so neither did
  the translation. `tr-ocrstat` names those files, and any PDF with no text
  layer yet. Step 6 reads each of them again, keeping the old copy as
  `<name>.txt.unmarked` and never writing over an earlier one — once
  `tesseract` and `pdftoppm` are installed; until then nothing can mark the
  layer, and it is left as it is. A project already translated from such
  layers: after step 6, `tr-run` drafts again every deliverable whose text
  layer changed.

#### 8. Translate

    tr-run -n                   # what it would draft, and why
    tr-run

Check the summary line — `translated`, `skipped`, `failed` — and the exit
status: `tr-run` exits 1 when a file failed.

Notes

- `tr-run` works from the inventory, not from a directory walk, so a file
  added to `source/` after the last `tr-inventory` is invisible to it: run
  step 5 again whenever you add anything. `tr-run` names any file it finds
  on disk that the inventory has never seen.
- Resumable at two levels: it skips a file whose deliverable is current, and
  within a file every segment already in the memory is reused. Interrupting
  it costs at most one segment.
- A deliverable is drafted again when anything that made it has changed
  since it was written — the source, a PDF's text layer, the glossary, the
  reference translations, the model, the prompt or the kit's drafting code —
  and the `redo` line says which; `tr-status` lists the same. A deliverable
  changed after `tr-run` wrote it, such as one a translator corrected in
  place, is never overwritten: it is listed as `kept`, and drafted again once
  it is moved aside.
- A segment the model could not translate is written `[TRANSLATION
  FAILED]`, and its file counts as failed: nothing is recorded for it, and
  the next run drafts it again.
- Where the references disagree, a draft carries `REF_OPTIONS`: search each
  deliverable for it, keep one rendering and delete the rest.
- **After updating the kit** nothing needs deleting. Run `tr-ref` where the
  project has references and step 6 where it has PDFs, then `tr-run` and
  `tr-lint`: every deliverable is drafted again once, from the memory, with
  today's conversions applied to rows written before them.

#### 9. Get the reviewer's worklist

    tr-lint

The translator works from `work/lint-report.tsv`, not from the raw draft.

Notes

- No model, seconds. It reports numbers dropped or invented,
  non-translatables altered, glossary terms not used, segments returned
  unchanged, and every `[TRANSLATION FAILED]` in a deliverable.

#### 10. Pin terminology, then draft again

    tr-terms --min-count 3 --pin-all

It writes `glossary/candidates.tsv`: terms the model rendered more than one
way, and frequent terms worth pinning before they drift. The translator
picks one rendering per line; the survivors go into `glossary/project.tsv`,
or into `_shared/glossary/base.tsv` if they are general legal vocabulary
that should outlive this matter. Then:

    tr-run
    tr-lint

Notes

- A pinned term changes the glossary every deliverable records, so `tr-run`
  drafts each file again, but only the segments containing the term go back
  to the model — minutes, not hours.

#### 11. Deliver into the archive

Once the translator has finished with `translated/` and `tr-status` shows
nothing missing or out of date, copy the originals and the translations
into this matter's folders in the archive:

    tr-status
    cp -av --update=none source/. <client>/in/356/
    cp -av --update=none translated/. <client>/out/356/

Check what `cp` printed: it names each file it copies. `--update=none`
copies nothing over a file already there, silently — so a file it does not
name was in the archive already, and is worth a look.

Notes

- `-a` keeps the folder tree and the files' dates. `cp -n` does the same as
  `--update=none` but is no longer portable, and `cp` warns about it.
- With `TR_SUFFIX=auto` each translation carries its language, so it can
  never take its original's name, and `tr-refimport` can later read the two
  folders as they are.

#### 12. Close

    cd ~ && case-close

Notes

- `cd` first, and not out of tidiness. A shell whose working directory is
  inside the container keeps the filesystem busy exactly as an open file
  does, so closing from within the project directory fails — and `-f` does
  not help, because the kernel counts a working directory as a use of the
  mount.
- Closing unmounts the container; it does not empty it. Everything stays
  inside the container file, encrypted, and returns at the next
  `case-open`. The corollary is retention: a finished matter occupies the
  container at full size until someone opens it and deletes the project
  directory by hand. No script removes client work.

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
