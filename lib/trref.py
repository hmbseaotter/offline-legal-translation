"""trref - reference translations: pairing, alignment, and exact reuse.

A matter often comes with earlier translations of the same kinds of document:
the same standard clauses, the same form labels, the same closing formulae. A
sentence a certifying translator has already rendered is better than any
draft the model can produce, and it costs no inference.

WHERE THEY GO -- inside the project, so inside the container:

    reference/leases/lease-2023_English.docx
    reference/leases/lease-2023_German.pdf

Anywhere under reference/, subfolders allowed. The two files of a pair sit in
the same folder and have the same name apart from a language suffix, the last
underscore-separated part before the extension: _English, _German, _Slovene,
or _EN, _DE, _SL, in any case. The extensions may differ, so a Word original
pairs with a PDF translation.

German takes a variant after a hyphen: _German-CH, _German-AT, and _German
or _German-DE for Germany. One English original can sit beside a Germany and
a Swiss translation, and each makes a pair of its own.

The suffix names a language, not a role. Which side is the source is the
project's TR_SRC, so the same pair would serve a German->English matter as
well as an English->German one, once a German source is supported. A file with no suffix is listed and skipped: guessing its
language would put it on the wrong side of a pair without a word.

WHY ONLY THE PROJECT'S OWN FOLDER

Invariant 9: translation memory never crosses matters. Reference translations
are sentences from some client's documents. Copying them into a project is a
decision the operator makes for that matter; nothing here looks beyond the
active project.

ALIGNMENT, WITHOUT A MODEL

Paragraphs first, then sentences inside each aligned paragraph, both by
dynamic programming over lengths (Gale & Church, 1993): a translation's
length is roughly proportional to its source's, so one sequence of lengths
lines up with the other. Numbers are the anchor. Dates, amounts and case
numbers keep their values through translation, and legal text is dense with
them, so two sentences whose numbers differ are not a pair.

Only one-to-one sentence pairs are kept, and only when their numbers agree,
their lengths are plausible, and neither side carries OCR_ILLEGIBLE. What is
kept may be reused verbatim, so the rules err towards keeping less. A pair
wrongly rejected costs one model call; a pair wrongly kept puts the
translation of a different sentence into a deliverable.

A pair is anchored when both sides carry the same numbers and no sentence
within three either side, in either document, carries those numbers too. An
anchored pair may be reused, and so may a pair between two anchored pairs,
which pin both documents on either side of it. Lengths cannot do that. Where
a translation omits a sentence, adds a note or swaps two, the one-to-one
pairs around the change still look right, so a pair with no anchor of its
own or either side -- no numbers, or numbers its neighbours share -- is never
reused. Where it lined up one-to-one among one-to-one neighbours it is
offered instead, tagged (unconfirmed), for the translator to confirm; beside
anything else it is rejected. tests/test_references.py sweeps omissions,
insertions and swaps, and fails if a wrong pair is kept for reuse.

EXACT REUSE

A source segment identical to a kept reference sentence, whitespace aside,
takes that translation with no model call, and never enters the translation
memory. Renderings that differ only in punctuation are one rendering, written
the way most documents write it. Case is not punctuation -- Sie and sie are
two words -- and nor are a minus sign, % or §. A mark between two digits
belongs to the number, so 5.1 and 51 remain two.

OPTIONS WHERE THE REFERENCES DISAGREE

Choosing between two human renderings is the translator's decision, so where
references disagree the draft carries the choice instead of a model draft, as
one token a search finds, like OCR_ILLEGIBLE:

    REF_OPTIONS [[Der Mieter kann kündigen.]] | [[Der Mieter darf kündigen.]]

Double square brackets rather than guillemets, because Swiss German writes its
quotation marks «…» and a Swiss rendering would carry them inside the token.

The rendering found in the most documents comes first -- counted once per
document, so a clause one file repeats does not outvote two files -- and a tie
goes to the newest, by the date the translation file says it was last saved:
Word's core properties, a PDF's ModDate. The date on disk will not do, since
copying a file resets it. A pinned glossary term that only one rendering uses
puts that rendering first, whatever the counts. The draft carries two;
tr-ref --conflicts lists every rendering with its count and the date that
ordered it, because an internal date can be meaningless -- a file python-docx
made says 2013-12-23 until something saves it.

A translation read by OCR is never reused on its own, because a misreading
would pass straight into a deliverable. It is offered instead, tagged (OCR),
where a person reads it before it stays. So is one rejoined at a line-end
hyphen that may have been the word's own, tagged (hyphenation), and one
lined up with nothing to confirm it, tagged (unconfirmed).

A German translation is reused only in a project writing its variant: a Swiss
one where TR_TGT is de-CH, a Germany one where it is de. Renderings in two
variants differ as a matter of course, so one is not a disagreement with the
other. Where the project's own variant has no reference for a sentence, the
other variant's renderings are offered, tagged with it -- [[…]] (de-CH) -- and
never reused. Offered to a Swiss project, a Germany rendering is first spelled
ss for ß, as a Swiss draft would be. The variant matters on the target side
only; a German source is refused for now (trlib.project_pair).
"""
import collections
import datetime
import hashlib
import math
import os
import re
import sqlite3
import subprocess
import sys
import unicodedata
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trlib  # noqa: E402

OCR_LANG = {"sl": "slv", "en": "eng", "de": "deu"}
EXTS = (".docx", ".pdf", ".txt")
MARK = os.environ.get("TR_ILLEGIBLE_MARK", "OCR_ILLEGIBLE")

# Gale & Church's variance of the length difference, per character.
S2 = 6.8
# What each bead shape costs before its lengths are weighed. One-to-one is
# the expected case; the others have to earn their place.
BEAD_PRIOR = {(1, 1): 0.0, (2, 1): 2.3, (1, 2): 2.3, (1, 0): 4.5, (0, 1): 4.5}
# Numbers that agree pull a bead together; numbers that disagree push it apart.
NUM_AGREE, NUM_DISAGREE = -1.5, 3.0


def norm(s):
    """What exact reuse compares: the text with its whitespace collapsed."""
    return " ".join((s or "").split())


# ------------------------------------------------------------------ pairing

# The language suffix: the last underscore-separated part of a file's name,
# with a variant after a hyphen where the language has them: _German-CH.
SUFFIX_LANG = {
    "english": "en", "en": "en",
    "german": "de", "deutsch": "de", "de": "de",
    "slovene": "sl", "slovenian": "sl", "sl": "sl",
}
_SUFFIX_RE = re.compile(
    r"^(?P<stem>.+)_(?P<lang>[A-Za-z]+)(?:-(?P<region>[A-Za-z]{2}))?$")


def file_language(name):
    """(stem, language) for 'lease-2023_German-CH.pdf', or (None, None).

    The language in trlib.lang_code()'s spelling: 'de-CH' here, and plain
    'de' for _German and _German-DE alike. A variant the language does not
    have -- _English-GB, _German-XX -- counts as no suffix, so the file is
    listed as unlabelled rather than filed as something it may not be.
    """
    m = _SUFFIX_RE.match(os.path.splitext(name)[0])
    lang = SUFFIX_LANG.get(m.group("lang").lower()) if m else None
    if lang and m.group("region"):
        lang = trlib.lang_code(f"{lang}-{m.group('region')}")
    return (m.group("stem"), lang) if lang else (None, None)


def _label(doc, lang):
    """A document's name, with its variant when that is not the language's
    first: 'leases/lease-2023 (de-CH)' beside 'leases/lease-2023'."""
    return f"{doc} ({lang})" if "-" in lang else doc


def find_pairs(src_lang, tgt_lang):
    """What is under the project's reference/ folder, sorted into pairs.

    pairs       [(doc, src_path, tgt_path, variant)], doc being folder/name,
                suffix off, and variant the German side's when it is not
                Germany -- 'de-CH' -- or ''. A Swiss pair's doc carries its
                variant, so it is a document of its own beside Germany's
    unpaired    [path] with a language suffix but no counterpart
    ambiguous   [doc] with two files in one language and variant
                (a_German.docx, a_German.pdf)
    unlabelled  [path] with no language suffix
    other       [path] in a language outside this project's pair
    """
    root = trlib.path("reference")
    src_lang, tgt_lang = trlib.base_lang(src_lang), trlib.base_lang(tgt_lang)
    # Each side keyed by name and variant: one original pairs with a Germany
    # translation and a Swiss one, and two files are ambiguous only when they
    # share both.
    sides = {src_lang: {}, tgt_lang: {}}
    amb, unlabelled, other = set(), [], []
    for dp, _dirs, files in os.walk(root):
        for f in sorted(files):
            if f.startswith((".", "~$")) or not f.lower().endswith(EXTS):
                continue
            full = os.path.join(dp, f)
            stem, code = file_language(f)
            if not code:
                unlabelled.append(full)
                continue
            lang = trlib.base_lang(code)
            if lang not in sides:
                other.append(full)
                continue
            doc = os.path.normpath(os.path.join(os.path.relpath(dp, root), stem))
            key = (doc.casefold(), code)   # Lease_English pairs with lease_German
            if key in sides[lang]:
                amb.add((lang, key))
            sides[lang][key] = (doc, full)
    s, t = sides[src_lang], sides[tgt_lang]
    t_codes = collections.defaultdict(list)
    for name, code in sorted(t):
        t_codes[name].append(code)
    pairs = []
    for name, scode in sorted(s):
        for tcode in t_codes.get(name, ()):
            if (src_lang, (name, scode)) in amb or (tgt_lang, (name, tcode)) in amb:
                continue
            variant = scode if "-" in scode else tcode if "-" in tcode else ""
            pairs.append((_label(s[(name, scode)][0], variant),
                          s[(name, scode)][1], t[(name, tcode)][1], variant))
    s_names = {name for name, _code in s}
    unpaired = sorted(
        [p for (name, _c), (_d, p) in s.items() if name not in t_codes] +
        [p for (name, _c), (_d, p) in t.items() if name not in s_names])
    ambiguous = sorted({_label(sides[lang][key][0], key[1]) for lang, key in amb})
    return pairs, unpaired, ambiguous, sorted(unlabelled), sorted(other)


# The alignment rules' version, recorded in each document's signature. A
# document aligned under older rules is aligned again by the next tr-ref, and
# until then load_references() does not reuse its pairs: a rule that keeps
# less protects nothing while the pairs an older rule kept are still stored.
ALIGN_VERSION = 2


def signature(*paths):
    """What a pair was aligned from: the rules' version and a hash of each
    file's contents. Size and modified time missed a file replaced by one of
    the same size whose time was kept, as cp -p keeps it."""
    parts = [f"a{ALIGN_VERSION}"]
    for p in paths:
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        parts.append(h.hexdigest()[:16])
    return "|".join(parts)


def current(sig):
    """Was a document with this signature aligned under today's rules?"""
    return (sig or "").split("|", 1)[0] == f"a{ALIGN_VERSION}"


# ------------------------------------------------------------- extraction

def _docx_paragraphs(path):
    """Body paragraphs and table cells, in document order.

    python-docx lists body paragraphs and tables separately, which loses
    where a table sits among the paragraphs -- and order is what alignment
    runs on. So the body is walked element by element. Merged cells repeat
    once per grid column and are taken once.
    """
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = docx.Document(path)
    out, seen = [], set()

    def cells(tbl):
        for row in tbl.rows:
            for cell in row.cells:
                if cell._tc in seen:
                    continue
                seen.add(cell._tc)
                for p in cell.paragraphs:
                    yield p.text
                for inner in cell.tables:
                    yield from cells(inner)

    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append(Paragraph(child, d).text)
        elif tag == "tbl":
            out.extend(cells(Table(child, d)))
    return [norm(p) for p in out if p.strip()]


# A word broken across two lines at a hyphen. Before a capital or a digit
# the hyphen belongs to the text and stays, with no space: Rhein-Main,
# EU-Richtlinie, 5-10. Before a lower-case letter nothing in the text says
# whether a word was hyphenated to fill the line, Verwaltungs-gericht, or
# broke at its own hyphen, self-employed. The likelier reading for the
# language is written -- German and Slovene hyphenate to fill a line, English
# seldom does -- and marked UNSURE, so that tr-ref offers the sentence rather
# than reusing it. settle() takes the mark out.
_HYPHEN_BREAK = re.compile(r"(\w)-[ \t]*\n[ \t]*(\w)")
UNSURE = "\ue000"
_HYPHENATES = {"de", "sl"}


def _blocks(text, lang=None):
    """Paragraphs of extracted text: blocks between blank lines, lines joined.

    A line break inside a block is layout, not a sentence boundary, and
    segment() treats every newline as one.
    """
    def rejoin(m):
        a, b = m.group(1), m.group(2)
        if not b.islower():
            return f"{a}-{b}"
        return f"{a}{UNSURE}{b}" if lang in _HYPHENATES else f"{a}-{UNSURE}{b}"

    out = []
    for block in re.split(r"\n\s*\n", text.replace("\f", "\n\n")):
        block = _HYPHEN_BREAK.sub(rejoin, block)
        joined = norm(block.replace("\n", " "))
        if joined:
            out.append(joined)
    return out


def settle(src, tgt, tags=()):
    """(src, tgt, tags) for a pair about to be stored, with the UNSURE marks
    taken out. A translation rejoined at an uncertain hyphen gains the tag
    HYPHENATION, which keeps it from reuse."""
    if UNSURE in tgt:
        tags = tuple(tags) + (HYPHENATION,)
    return src.replace(UNSURE, ""), tgt.replace(UNSURE, ""), tuple(tags)


def _pdf_paragraphs(path, lang):
    """The text layer tr-pdf makes, read in this side's OCR language.

    Through tr-pdf so there is one way to decide born-digital against scan
    and one way to OCR. Returns (paragraphs, how), how being "pdf-text" for
    a born-digital file and "pdf-ocr" for a scan: tr-pdf writes <name>.ocr.pdf
    beside the text layer only when it OCR'd.
    """
    tr_pdf = os.path.join(trlib.KIT_DIR, "bin", "tr-pdf")
    env = dict(os.environ, TR_OCR_LANGS=OCR_LANG.get(lang, "eng"))
    r = subprocess.run([tr_pdf, "--ocr-only", path], capture_output=True,
                       text=True, env=env, timeout=6 * 3600)
    m = re.search(r"^\s*text layer: (.+?)  \(\d+ words\)\s*$", r.stdout, re.M)
    if r.returncode != 0 or not m:
        raise RuntimeError(f"tr-pdf exit {r.returncode}")
    txt = m.group(1)
    how = "pdf-ocr" if os.path.exists(txt[:-len(".txt")] + ".ocr.pdf") \
        else "pdf-text"
    with open(txt, encoding="utf-8", errors="replace") as fh:
        return _blocks(fh.read(), lang), how


def paragraphs(path, lang):
    """(paragraphs, how) for one reference file."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return _docx_paragraphs(path), "docx"
    if ext == ".txt":
        with open(path, encoding="utf-8", errors="replace") as fh:
            return _blocks(fh.read(), lang), "txt"
    return _pdf_paragraphs(path, lang)


# --------------------------------------------------------------- alignment

def _bead_cost(la, lb, ratio, na, nb, shape):
    c = BEAD_PRIOR[shape]
    if la and lb:
        delta = (lb - la * ratio) / math.sqrt(max(la, 1) * S2)
        c += delta * delta / 2
        if na or nb:
            c += NUM_AGREE if na == nb else NUM_DISAGREE
    return c


def _counts(cs, lo, hi):
    if hi - lo == 1:
        return cs[lo]
    out = collections.Counter()
    for k in range(lo, hi):
        out += cs[k]
    return out


def align(a, b, ratio):
    """Beads (i0, i1, j0, j1) covering both sequences at least total cost.

    Searched first within a band around the diagonal -- a translation does
    not move a sentence from the start of a document to its end, and the
    full table is quadratic in document length -- and over the whole table
    only if the band cannot reach the end.
    """
    n, m = len(a), len(b)
    if not n or not m:
        return []
    la = [len(x) for x in a]
    lb = [len(x) for x in b]
    na = [trlib.norm_nums(x) for x in a]
    nb = [trlib.norm_nums(x) for x in b]
    inf = float("inf")
    for band in (max(20, max(n, m) // 10), None):
        cost = [[inf] * (m + 1) for _ in range(n + 1)]
        back = [[None] * (m + 1) for _ in range(n + 1)]
        cost[0][0] = 0.0
        for i in range(n + 1):
            if band is None:
                lo, hi = 0, m
            else:
                centre = i * m // n
                lo, hi = max(0, centre - band), min(m, centre + band)
            for j in range(lo, hi + 1):
                if i == 0 and j == 0:
                    continue
                best, arg = inf, None
                for di, dj in BEAD_PRIOR:
                    if i < di or j < dj or cost[i - di][j - dj] == inf:
                        continue
                    sa = sum(la[i - di:i]) + max(di - 1, 0)
                    sb = sum(lb[j - dj:j]) + max(dj - 1, 0)
                    c = cost[i - di][j - dj] + _bead_cost(
                        sa, sb, ratio, _counts(na, i - di, i),
                        _counts(nb, j - dj, j), (di, dj))
                    if c < best:
                        best, arg = c, (di, dj)
                cost[i][j], back[i][j] = best, arg
        if cost[n][m] < inf:
            break
    beads, i, j = [], n, m
    while i or j:
        di, dj = back[i][j]
        beads.append((i - di, i, j - dj, j))
        i, j = i - di, j - dj
    return beads[::-1]


# A number agreeing on both sides anchors a pair only when it tells the pair
# from its neighbours: two sentences in a row with the same numbers could
# swap places, or shift past a missing sentence, and still agree.
ANCHOR_WINDOW = 3


def _length_ok(s, t, ratio):
    return len(s) < 20 or 0.5 <= len(t) / (len(s) * ratio) <= 2.0


def _judge(s, t, ratio):
    """None when the pair may be kept, otherwise the reason it may not."""
    if MARK in s or MARK in t:
        return "illegible"
    if not trlib.is_translatable(s):
        return "not translatable"
    if norm(s) == norm(t):
        return "untranslated"
    if trlib.norm_nums(s) != trlib.norm_nums(t):
        return "numbers differ"
    if not _length_ok(s, t, ratio):
        return "length"
    return None


def align_document(src_paras, tgt_paras, by_paragraph=True):
    """(kept, rejected): [(src, tgt, confirmed)] and [(src, tgt, reason)],
    each in document order.

    by_paragraph lines up paragraphs before sentences, which is both faster
    and more reliable -- when both sides have real paragraphs. Text taken
    from a PDF does not: a page's blank lines are layout, and a scan's text
    layer is one block a page. With either side from a PDF, sentences are
    lined up across the whole document instead.

    A confirmed pair may be reused: it is anchored by numbers that it and
    its counterpart carry and their neighbours do not, or sits between two
    anchored pairs. An unconfirmed one lined up one-to-one among one-to-one
    neighbours with nothing to anchor it, and is offered for the translator
    to confirm. The module docstring says why.
    """
    ls = sum(len(p) for p in src_paras)
    lt = sum(len(p) for p in tgt_paras)
    ratio = min(2.0, max(0.5, lt / ls)) if ls and lt else 1.0
    if by_paragraph:
        spans = align(src_paras, tgt_paras, ratio)
    else:
        spans = [(0, len(src_paras), 0, len(tgt_paras))]

    # Every sentence bead in document order: its sentences on each side,
    # whether its paragraph lined up one-to-one, and where its first sentence
    # stands in each document. A paragraph with no counterpart is a bead too,
    # and not a one-to-one one, so no pair vouches across it. A newline
    # between paragraphs keeps a heading from running into the next sentence.
    seq, src_all, tgt_all = [], [], []
    for i0, i1, j0, j1 in spans:
        ss = trlib.segment("\n".join(src_paras[i0:i1])) if i1 > i0 else []
        ts = trlib.segment("\n".join(tgt_paras[j0:j1])) if j1 > j0 else []
        if ss and ts:
            para_ok = not by_paragraph or (i1 - i0, j1 - j0) == (1, 1)
            for a, b, c, d in align(ss, ts, ratio):
                seq.append((ss[a:b], ts[c:d], para_ok,
                            len(src_all) + a, len(tgt_all) + c))
        elif ss or ts:
            seq.append((ss, ts, False, len(src_all), len(tgt_all)))
        src_all.extend(ss)
        tgt_all.extend(ts)
    ns = [trlib.norm_nums(x) for x in src_all]
    nt = [trlib.norm_nums(x) for x in tgt_all]

    def alone(nums, i):
        return all(nums[k] != nums[i]
                   for k in range(max(0, i - ANCHOR_WINDOW),
                                  min(len(nums), i + ANCHOR_WINDOW + 1))
                   if k != i)

    one = [len(s) == 1 and len(t) == 1 and ok for s, t, ok, _i, _j in seq]
    anchored = [one[k] and bool(ns[i]) and ns[i] == nt[j]
                and MARK not in s[0] and MARK not in t[0]
                and _length_ok(s[0], t[0], ratio)
                and alone(ns, i) and alone(nt, j)
                for k, (s, t, _ok, i, j) in enumerate(seq)]
    why = [_judge(s[0], t[0], ratio) if one[k] else "not one-to-one"
           for k, (s, t, _ok, _i, _j) in enumerate(seq)]
    # A neighbour whose numbers or length disagree is a sign that the two
    # documents part company there, whatever its shape.
    sound = [one[k] and why[k] not in ("numbers differ", "length")
             for k in range(len(seq))]
    kept, rejected = [], []
    for k, (s, t, _ok, _i, _j) in enumerate(seq):
        if not one[k]:
            if s and t:
                rejected.append((" ".join(s), " ".join(t), why[k]))
        elif why[k]:
            rejected.append((s[0], t[0], why[k]))
        elif anchored[k] or (0 < k < len(seq) - 1
                             and anchored[k - 1] and anchored[k + 1]):
            kept.append((s[0], t[0], True))
        elif (k == 0 or sound[k - 1]) and (k == len(seq) - 1 or sound[k + 1]):
            kept.append((s[0], t[0], False))
        else:
            rejected.append((s[0], t[0], "no anchor"))
    return kept, rejected


# ------------------------------------------------------------------- dates

_CORE_DATE = re.compile(
    r"<dcterms:(modified|created)\b[^>]*>\s*([^<\s]+)\s*</dcterms:\1>")
_PDF_DATE = re.compile(r"^(ModDate|CreationDate):\s+(\S+)\s*$", re.M)


def _utc(value):
    """An ISO 8601 date as UTC, '2024-03-01T11:00:00Z', or '' if it is not
    one. One spelling, so that dates compare as strings."""
    v = (value or "").strip().replace("Z", "+00:00")
    if re.search(r"[+-]\d\d$", v):                  # pdfinfo writes +01
        v += ":00"
    try:
        d = datetime.datetime.fromisoformat(v)
    except ValueError:
        return ""
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_date(path):
    """(date, where it came from) for a translation file: the date the file
    itself says it was last saved, as UTC, or ('', 'no date').

    Read from inside the file because the date on disk does not survive a
    copy: cp gives the copy today's date, and cp -p keeps only the modified
    time. Word keeps the date in its core properties, a PDF in ModDate. Where
    that is missing the created date stands in, since a file saved once was
    last saved when it was made. Plain text records no date.
    """
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".docx":
            with zipfile.ZipFile(path) as z:
                core = z.read("docProps/core.xml").decode("utf-8", "replace")
            found = {("Word last saved" if k == "modified" else "Word created"): v
                     for k, v in _CORE_DATE.findall(core)}
            order = ("Word last saved", "Word created")
        elif ext == ".pdf":
            r = subprocess.run(["pdfinfo", "-isodates", path],
                               capture_output=True, text=True, timeout=60)
            found = {f"PDF {k}": v for k, v in _PDF_DATE.findall(r.stdout)}
            order = ("PDF ModDate", "PDF CreationDate")
        else:
            return "", "no date"
    except (OSError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError):
        return "", "no date"
    for label in order:
        if _utc(found.get(label)):
            return _utc(found[label]), label
    return "", "no date"


# ------------------------------------------------------------------- store

def store_path():
    return trlib.path("work", "reference.sqlite")


def _columns(db, table):
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}


def open_store():
    os.makedirs(trlib.path("work"), exist_ok=True)
    db = sqlite3.connect(store_path(), timeout=60)
    db.execute("""CREATE TABLE IF NOT EXISTS pairs(
        direction TEXT, doc TEXT, src TEXT, src_norm TEXT, tgt TEXT,
        how TEXT, reusable INTEGER, variant TEXT NOT NULL DEFAULT '',
        offered TEXT NOT NULL DEFAULT '')""")
    if "variant" not in _columns(db, "pairs"):
        # A store written before variants. Every German file in it was named
        # without one, and a German suffix without a variant is Germany.
        db.execute("ALTER TABLE pairs ADD COLUMN variant TEXT NOT NULL DEFAULT ''")
    if "offered" not in _columns(db, "pairs"):
        # A store written before tags: every pair in it that may not be
        # reused was read by OCR, and kept() says so.
        db.execute("ALTER TABLE pairs ADD COLUMN offered TEXT NOT NULL DEFAULT ''")
    db.execute("CREATE INDEX IF NOT EXISTS pairs_src ON pairs(direction, src_norm)")
    db.execute("""CREATE TABLE IF NOT EXISTS docs(
        direction TEXT, doc TEXT, signature TEXT, kept INTEGER,
        rejected TEXT, date TEXT NOT NULL DEFAULT '',
        date_from TEXT NOT NULL DEFAULT '', PRIMARY KEY(direction, doc))""")
    for col in ("date", "date_from"):
        if col not in _columns(db, "docs"):
            # A store written before dates; tr-ref fills them in as it runs.
            db.execute(f"ALTER TABLE docs ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
    return db


def reuse_direction(direction, variant):
    """The direction a kept pair is reused in.

    Pairs are aligned and stored per language pair: a Swiss translation of an
    English original under en-de, beside Germany's. Where the German side is
    the target and not Germany's, the pair is reused only in its variant's
    own direction, en-de-CH -- the direction tr-run translates in when
    TR_TGT is de-CH. Every other pair is reused in the direction it is stored
    under.
    """
    s, t = trlib.split_direction(direction)
    return f"{s}-{variant}" if variant and trlib.base_lang(variant) == t \
        else direction


def kept(db, direction=None, offered=False):
    """(reuse direction, doc, src, src_norm, tgt, how, reusable) for each kept
    pair, in document order -- and with offered set, an eighth field: the tags
    it is offered under. Given a direction, only the pairs stored for its
    language pair -- in every variant, so a caller wanting one variant
    compares the first field. Reads a store from before variants as
    Germany's, and one from before tags as offered for OCR alone.
    """
    cols = _columns(db, "pairs")
    variant = "variant" if "variant" in cols else "''"
    tags = "offered" if "offered" in cols else "''"
    sql = (f"SELECT direction, doc, src, src_norm, tgt, how, reusable, {variant}, "
           f"{tags} FROM pairs")
    args = ()
    if direction:
        s, t = trlib.split_direction(direction)
        sql, args = sql + " WHERE direction = ?", (f"{s}-{trlib.base_lang(t)}",)
    for d, doc, src, src_norm, tgt, how, reusable, var, why in db.execute(
            sql + " ORDER BY doc, rowid", args):
        row = (reuse_direction(d, var), doc, src, src_norm, tgt, how, reusable)
        if offered:
            row += (tuple(why.split(",")) if why else () if reusable else (OCR,),)
        yield row


# ------------------------------------------------------------------- reuse

# One kept pair, as reuse sees it: the direction it is reused in, its
# document, the translation, whether it may be reused, the date the
# translation file records, and the tags it is offered under when it may not.
Row = collections.namedtuple(
    "Row", "direction doc tgt reusable date date_from offered", defaults=((),))

# Why a pair is offered rather than reused, each written as a tag beside it in
# the draft: its document was read by OCR; it was rejoined at a line-end
# hyphen that may have been the word's own; nothing confirms its alignment.
OCR, HYPHENATION, UNCONFIRMED = "OCR", "hyphenation", "unconfirmed"

OPTIONS_MARK = "REF_OPTIONS"
OPTIONS_OPEN, OPTIONS_CLOSE = "[[", "]]"


def load_references():
    """{language pair: {normalised source: [Row]}}: every kept pair, for
    resolve() to decide what each sentence gets. Reads a store from before
    dates, whose documents then have none.

    A document aligned under older rules than ALIGN_VERSION contributes
    nothing until tr-ref aligns it again, and a line on stderr says so."""
    if not os.path.exists(store_path()):
        return {}
    db = sqlite3.connect(store_path(), timeout=60)
    dated = {"date", "date_from"} <= _columns(db, "docs")
    docs = {}
    for row in db.execute("SELECT direction, doc, signature"
                          + (", date, date_from" if dated else "") + " FROM docs"):
        docs[row[0], row[1]] = (current(row[2]),) + (tuple(row[3:]) if dated else ("", ""))
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    stale = set()
    for d, doc, _src, src_norm, tgt, _how, reusable, tags in kept(db, offered=True):
        s, t = trlib.split_direction(d)
        pair = f"{s}-{trlib.base_lang(t)}"
        ok, date, date_from = docs.get((pair, doc), (False, "", ""))
        if not ok:
            stale.add((pair, doc))
            continue
        out[pair][src_norm].append(
            Row(d, doc, tgt, reusable, date, date_from or "no date", tags))
    db.close()
    if stale:
        sys.stderr.write(f"  {len(stale)} reference document(s) were aligned "
                         f"under older rules and are not reused until tr-ref "
                         f"runs again\n")
    return {pair: dict(sources) for pair, sources in out.items()}


def digest(direction):
    """What reuse reads for this direction's language pair, as one hash:
    every kept pair with its tags, and each document's signature and date.
    tr-run records it with each deliverable, so a file drafted before tr-ref
    kept a sentence, or before a reference changed, is drafted again. "-"
    when there is no store."""
    if not os.path.exists(store_path()):
        return "-"
    db = sqlite3.connect(store_path(), timeout=60)
    s, t = trlib.split_direction(direction)
    h = hashlib.sha256()
    for row in kept(db, direction, offered=True):
        h.update(repr(row).encode())
    dated = "date" in _columns(db, "docs")
    for row in db.execute("SELECT doc, signature" + (", date" if dated else "")
                          + " FROM docs WHERE direction = ? ORDER BY doc",
                          (f"{s}-{trlib.base_lang(t)}",)):
        h.update(repr(row).encode())
    db.close()
    return h.hexdigest()[:16]


def rendering_key(text):
    """What renderings share when they differ only in punctuation.

    Case is kept: Sie and sie are two words in German, the polite you and
    they. A mark between two digits is part of the number, so 5.1 and 51 stay
    two, and a hyphen before a digit with no word before it is a minus sign,
    so -250,00 and 250,00 stay two. % and § are words written as signs.
    """
    t = norm(text)
    out = []
    for i, c in enumerate(t):
        digit_before = i > 0 and t[i - 1].isdigit()
        digit_after = i < len(t) - 1 and t[i + 1].isdigit()
        sign = c == "-" and digit_after and not (i > 0 and t[i - 1].isalnum())
        out.append(" " if unicodedata.category(c).startswith("P")
                   and not (digit_before and digit_after) and not sign
                   and c not in "%‰§" else c)
    return " ".join("".join(out).split())


def _ranked(items, count, date, name, first=lambda _item: 0):
    """items by first, then count, then newest date, then name. Two sorts,
    because a date string cannot be negated into one key: the second keeps
    the name order among equals, and reverse=True keeps a sort stable."""
    out = sorted(items, key=name)
    out.sort(key=lambda i: (first(i), count(i), date(i)), reverse=True)
    return out


class Rendering:
    """One way the references render a sentence: every spelling of it that
    differs only in punctuation, with what orders it."""

    def __init__(self, rows):
        clean = [r for r in rows if r.reusable]
        self.rows = rows
        # Why it is offered rather than reused, when no copy of it may be
        # reused. A row that may not be and names no tag is OCR's.
        self.offered = [] if clean else sorted(
            {tag for r in rows for tag in (r.offered or (OCR,))})
        self.docs = {r.doc for r in rows}
        newest = max(rows, key=lambda r: r.date)
        self.date, self.date_from, self.date_doc = \
            newest.date, newest.date_from, newest.doc
        self.variants = sorted({trlib.split_direction(r.direction)[1] for r in rows})
        # The spelling most documents use, taken from a copy not read by OCR
        # whenever there is one.
        spellings = collections.defaultdict(list)
        for r in clean or rows:
            spellings[norm(r.tgt)].append(r)
        self.text = _ranked(spellings,
                            count=lambda s: len({r.doc for r in spellings[s]}),
                            date=lambda s: max(r.date for r in spellings[s]),
                            name=lambda s: s)[0]
        self.tags = []


def _variant_label(code):
    """'de-DE' for Germany's plain 'de': a tag has to say which variant."""
    lang = trlib.base_lang(code)
    if "-" in code or lang not in trlib.VARIANTS:
        return code
    return f"{lang}-{trlib.VARIANTS[lang][0]}"


def resolve(rows, direction, source, gloss=None):
    """What tr-run writes for one source sentence, given the kept pairs of its
    language pair that translate it: (text, shown, ranked).

    text is the reused translation or a REF_OPTIONS token; shown the
    renderings written into it; ranked every rendering considered, in order.
    The project's own variant's renderings are considered when there are any,
    another variant's only when there are none. One rendering is reused,
    unless no copy of it may be -- read by OCR, rejoined at an uncertain
    line-end hyphen, or lined up with nothing to confirm it -- or it is
    another variant's; anything else is offered, at most two at a time.
    """
    own = [r for r in rows if r.direction == direction]
    pool = own or rows
    if not own and trlib.split_direction(direction)[1] == "de-CH":
        # Another variant's renderings, offered to a Swiss project, in the
        # spelling a Swiss draft would have.
        pool = [r._replace(tgt=trlib.swiss_spelling(source, r.tgt)) for r in pool]
    groups = collections.defaultdict(list)
    for r in pool:
        groups[rendering_key(r.tgt)].append(r)
    renderings = [Rendering(g) for g in groups.values()]

    # A pinned term that only one rendering uses picks that rendering.
    low = (source or "").lower()
    picks = collections.Counter()
    for term, target in gloss or ():
        if term.lower() in low:
            having = [g for g in renderings if target.lower() in g.text.lower()]
            if len(having) == 1:
                picks[id(having[0])] += 1
    ranked = _ranked(renderings, first=lambda g: picks[id(g)],
                     count=lambda g: len(g.docs), date=lambda g: g.date,
                     name=lambda g: g.text)

    if own and len(ranked) == 1 and not ranked[0].offered:
        return ranked[0].text, ranked[:1], ranked
    for g in ranked:
        g.tags = ([] if own else [_variant_label(v) for v in g.variants]) \
            + g.offered
    shown = ranked[:2]
    text = OPTIONS_MARK + " " + " | ".join(
        f"{OPTIONS_OPEN}{g.text}{OPTIONS_CLOSE}"
        + (f" ({', '.join(g.tags)})" if g.tags else "")
        for g in shown)
    return text, shown, ranked
