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
project's TR_SRC, so the same pair serves an English->German matter and a
German->English one. A file with no suffix is listed and skipped: guessing its
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
their lengths are plausible, and neither side carries OCR_ILLEGIBLE. A
sentence with no number is kept only where the structure vouches for it: its
paragraph lined up one-to-one and every sentence in that paragraph did too.
What is kept may be reused verbatim, so the rules err towards keeping less. A
pair wrongly rejected costs one model call; a pair wrongly kept puts the
translation of a different sentence into a deliverable.

EXACT REUSE

A source segment identical to a kept reference sentence, whitespace aside,
takes that translation with no model call, and never enters the translation
memory. Renderings that differ only in case or punctuation are one rendering,
written the way most documents write it. A mark between two digits belongs to
the number, so 5.1 and 51 remain two.

OPTIONS WHERE THE REFERENCES DISAGREE

Choosing between two human renderings is the translator's decision, so where
references disagree the draft carries the choice instead of a model draft, as
one token a search finds, like OCR_ILLEGIBLE:

    REF_OPTIONS «Der Mieter kann kündigen.» | «Der Mieter darf kündigen.»

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
where a person reads it before it stays.

A German translation is reused only in a project writing its variant: a Swiss
one where TR_TGT is de-CH, a Germany one where it is de. Renderings in two
variants differ as a matter of course, so one is not a disagreement with the
other. Where the project's own variant has no reference for a sentence, the
other variant's renderings are offered, tagged with it -- «…» (de-CH) -- and
never reused. The variant matters on the target side only; a German->English
project reuses a pair whatever German its source is written in.
"""
import collections
import datetime
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


def signature(*paths):
    """Size and mtime of each file: enough to notice that one was replaced."""
    parts = []
    for p in paths:
        st = os.stat(p)
        parts.append(f"{st.st_size}:{st.st_mtime:.0f}")
    return "|".join(parts)


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


_HYPHEN_BREAK = re.compile(r"(\w)-\n(?=[a-zäöüßčšž])")


def _blocks(text):
    """Paragraphs of extracted text: blocks between blank lines, lines joined.

    A line break inside a block is layout, not a sentence boundary, and
    segment() treats every newline as one. A word hyphenated across lines is
    rejoined only when the next line starts in lower case: German capitalises
    nouns, so "Verwaltungs-\\ngericht" is one word and "Rhein-\\nMain" is two.
    """
    out = []
    for block in re.split(r"\n\s*\n", text.replace("\f", "\n\n")):
        block = _HYPHEN_BREAK.sub(r"\1", block)
        joined = norm(block.replace("\n", " "))
        if joined:
            out.append(joined)
    return out


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
        return _blocks(fh.read()), how


def paragraphs(path, lang):
    """(paragraphs, how) for one reference file."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return _docx_paragraphs(path), "docx"
    if ext == ".txt":
        with open(path, encoding="utf-8", errors="replace") as fh:
            return _blocks(fh.read()), "txt"
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


def _judge(s, t, ratio, structural):
    """None when the pair is kept, otherwise the reason it is not."""
    if MARK in s or MARK in t:
        return "illegible"
    if not trlib.is_translatable(s):
        return "not translatable"
    if norm(s) == norm(t):
        return "untranslated"
    ns, nt = trlib.norm_nums(s), trlib.norm_nums(t)
    if ns != nt:
        return "numbers differ"
    if len(s) >= 20:
        r = len(t) / (len(s) * ratio)
        if not 0.5 <= r <= 2.0:
            return "length"
    if not ns and not structural:
        return "no anchor"
    return None


def align_document(src_paras, tgt_paras, by_paragraph=True):
    """(kept, rejected): [(src, tgt)] and [(src, tgt, reason)].

    by_paragraph lines up paragraphs before sentences, which is both faster
    and more reliable -- when both sides have real paragraphs. Text taken
    from a PDF does not: a page's blank lines are layout, and a scan's text
    layer is one block a page. With either side from a PDF, sentences are
    lined up across the whole document instead.

    A sentence with no number to anchor it is kept only when the sentences
    either side of it also lined up one-to-one. A run of clean one-to-one
    pairs is the evidence that the two documents really do correspond there.
    """
    ls = sum(len(p) for p in src_paras)
    lt = sum(len(p) for p in tgt_paras)
    ratio = min(2.0, max(0.5, lt / ls)) if ls and lt else 1.0
    if by_paragraph:
        spans = align(src_paras, tgt_paras, ratio)
    else:
        spans = [(0, len(src_paras), 0, len(tgt_paras))]

    # Every sentence bead in document order, with whether its paragraph
    # lined up one-to-one. A newline between paragraphs keeps a heading from
    # running into the sentence after it.
    seq = []
    for i0, i1, j0, j1 in spans:
        if i0 == i1 or j0 == j1:
            continue                      # a paragraph with no counterpart
        ss = trlib.segment("\n".join(src_paras[i0:i1]))
        ts = trlib.segment("\n".join(tgt_paras[j0:j1]))
        para_ok = not by_paragraph or (i1 - i0, j1 - j0) == (1, 1)
        for a, b, c, d in align(ss, ts, ratio):
            seq.append((ss[a:b], ts[c:d], para_ok))

    one = [len(s) == 1 and len(t) == 1 and ok for s, t, ok in seq]
    kept, rejected = [], []
    for k, (s, t, _ok) in enumerate(seq):
        if not one[k]:
            if s and t:
                rejected.append((" ".join(s), " ".join(t), "not one-to-one"))
            continue
        structural = ((k == 0 or one[k - 1])
                      and (k == len(seq) - 1 or one[k + 1]))
        why = _judge(s[0], t[0], ratio, structural)
        if why:
            rejected.append((s[0], t[0], why))
        else:
            kept.append((s[0], t[0]))
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
        how TEXT, reusable INTEGER, variant TEXT NOT NULL DEFAULT '')""")
    if "variant" not in _columns(db, "pairs"):
        # A store written before variants. Every German file in it was named
        # without one, and a German suffix without a variant is Germany.
        db.execute("ALTER TABLE pairs ADD COLUMN variant TEXT NOT NULL DEFAULT ''")
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
    under, so a German->English project takes a sentence whichever German its
    source was written in.
    """
    s, t = trlib.split_direction(direction)
    return f"{s}-{variant}" if variant and trlib.base_lang(variant) == t \
        else direction


def kept(db, direction=None):
    """(reuse direction, doc, src, src_norm, tgt, how, reusable) for each kept
    pair, in document order. Given a direction, only the pairs stored for its
    language pair -- in every variant, so a caller wanting one variant
    compares the first field. Reads a store from before variants as Germany's.
    """
    variant = "variant" if "variant" in _columns(db, "pairs") else "''"
    sql = (f"SELECT direction, doc, src, src_norm, tgt, how, reusable, {variant} "
           f"FROM pairs")
    args = ()
    if direction:
        s, t = trlib.split_direction(direction)
        sql, args = sql + " WHERE direction = ?", (f"{s}-{trlib.base_lang(t)}",)
    for d, doc, src, src_norm, tgt, how, reusable, var in db.execute(
            sql + " ORDER BY doc, rowid", args):
        yield reuse_direction(d, var), doc, src, src_norm, tgt, how, reusable


# ------------------------------------------------------------------- reuse

# One kept pair, as reuse sees it: the direction it is reused in, its
# document, the translation, whether that was read without OCR, and the date
# the translation file records.
Row = collections.namedtuple("Row", "direction doc tgt reusable date date_from")

OPTIONS_MARK = "REF_OPTIONS"


def load_references():
    """{language pair: {normalised source: [Row]}}: every kept pair, for
    resolve() to decide what each sentence gets. Reads a store from before
    dates, whose documents then have none."""
    if not os.path.exists(store_path()):
        return {}
    db = sqlite3.connect(store_path(), timeout=60)
    dates = {}
    if {"date", "date_from"} <= _columns(db, "docs"):
        dates = {(d, doc): (date, date_from) for d, doc, date, date_from in
                 db.execute("SELECT direction, doc, date, date_from FROM docs")}
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    for d, doc, _src, src_norm, tgt, _how, reusable in kept(db):
        s, t = trlib.split_direction(d)
        pair = f"{s}-{trlib.base_lang(t)}"
        date, date_from = dates.get((pair, doc), ("", ""))
        out[pair][src_norm].append(
            Row(d, doc, tgt, reusable, date, date_from or "no date"))
    db.close()
    return {pair: dict(sources) for pair, sources in out.items()}


def rendering_key(text):
    """What renderings share when they differ only in case and punctuation.

    A mark between two digits is part of the number rather than punctuation,
    so 5.1 and 51 stay two renderings. lower(), not casefold(): casefold
    writes ß as ss, which is spelling -- and the very difference between
    Germany and Switzerland.
    """
    t = norm(text).lower()
    out = []
    for i, c in enumerate(t):
        in_number = 0 < i < len(t) - 1 and t[i - 1].isdigit() and t[i + 1].isdigit()
        out.append(" " if unicodedata.category(c).startswith("P")
                   and not in_number else c)
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
    differs only in case and punctuation, with what orders it."""

    def __init__(self, rows):
        clean = [r for r in rows if r.reusable]
        self.rows = rows
        self.ocr = not clean                   # every copy of it read by OCR
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
    unless every copy of it was read by OCR or it is another variant's;
    anything else is offered, at most two at a time.
    """
    own = [r for r in rows if r.direction == direction]
    groups = collections.defaultdict(list)
    for r in own or rows:
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

    if own and len(ranked) == 1 and not ranked[0].ocr:
        return ranked[0].text, ranked[:1], ranked
    for g in ranked:
        g.tags = ([] if own else [_variant_label(v) for v in g.variants]) \
            + (["OCR"] if g.ocr else [])
    shown = ranked[:2]
    text = OPTIONS_MARK + " " + " | ".join(
        f"«{g.text}»" + (f" ({', '.join(g.tags)})" if g.tags else "")
        for g in shown)
    return text, shown, ranked
