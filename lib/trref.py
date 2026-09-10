"""trref - reference translations: pairing, alignment, and exact reuse.

A matter often comes with earlier translations of the same kinds of document:
the same standard clauses, the same form labels, the same closing formulae. A
sentence a certifying translator has already rendered is better than any
draft the model can produce, and it costs no inference.

WHERE THEY GO -- inside the project, so inside the container:

    reference/en/leases/lease-2023.docx
    reference/de/leases/lease-2023.pdf

The two folders are named by the project's TR_SRC and TR_TGT. A pair is the
same path on both sides, extension aside, so a Word original may be paired
with a PDF translation.

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
takes that translation with no model call -- with two exceptions. When
references disagree about the same sentence, none is used: choosing between
two human renderings is the translator's decision, and tr-ref lists them. And
a translation read by OCR is never reused verbatim, because an OCR misreading
would pass straight into a deliverable; such pairs still count for
terminology, where a person reads every proposal.
"""
import collections
import math
import os
import re
import sqlite3
import subprocess
import sys

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

def find_pairs(src_lang, tgt_lang):
    """(pairs, unpaired, ambiguous) under the project's reference/ folder.

    pairs      [(doc, src_path, tgt_path)], doc being the shared stem
    unpaired   [path] present on one side only
    ambiguous  [stem] with more than one file on a side (a.docx and a.pdf)
    """
    root = trlib.path("reference")
    sides = {}
    ambiguous = set()
    for lang in (src_lang, tgt_lang):
        base = os.path.join(root, lang)
        found = {}
        for dp, _dirs, files in os.walk(base):
            for f in sorted(files):
                if f.startswith((".", "~$")) or not f.lower().endswith(EXTS):
                    continue
                full = os.path.join(dp, f)
                stem = os.path.splitext(os.path.relpath(full, base))[0]
                if stem in found:
                    ambiguous.add(stem)
                found[stem] = full
        sides[lang] = found
    s, t = sides[src_lang], sides[tgt_lang]
    pairs = [(stem, s[stem], t[stem]) for stem in sorted(s)
             if stem in t and stem not in ambiguous]
    unpaired = sorted([s[k] for k in s if k not in t] +
                      [t[k] for k in t if k not in s])
    return pairs, unpaired, sorted(ambiguous)


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


# ------------------------------------------------------------------- store

def store_path():
    return trlib.path("work", "reference.sqlite")


def open_store():
    os.makedirs(trlib.path("work"), exist_ok=True)
    db = sqlite3.connect(store_path(), timeout=60)
    db.execute("""CREATE TABLE IF NOT EXISTS pairs(
        direction TEXT, doc TEXT, src TEXT, src_norm TEXT, tgt TEXT,
        how TEXT, reusable INTEGER)""")
    db.execute("CREATE INDEX IF NOT EXISTS pairs_src ON pairs(direction, src_norm)")
    db.execute("""CREATE TABLE IF NOT EXISTS docs(
        direction TEXT, doc TEXT, signature TEXT, kept INTEGER,
        rejected TEXT, PRIMARY KEY(direction, doc))""")
    return db


def load_reuse():
    """{direction: {normalised source: translation}}, reusable and agreed only."""
    if not os.path.exists(store_path()):
        return {}
    db = sqlite3.connect(store_path(), timeout=60)
    seen = collections.defaultdict(set)
    usable = set()
    for direction, src_norm, tgt, reusable in db.execute(
            "SELECT direction, src_norm, tgt, reusable FROM pairs"):
        seen[(direction, src_norm)].add(norm(tgt))
        if reusable:
            usable.add((direction, src_norm, tgt))
    db.close()
    out = collections.defaultdict(dict)
    for direction, src_norm, tgt in usable:
        if len(seen[(direction, src_norm)]) == 1:
            out[direction][src_norm] = tgt
    return dict(out)


def conflicts(db, direction):
    """[(source, [translations])] the references render more than one way."""
    by = collections.defaultdict(set)
    for src_norm, tgt in db.execute(
            "SELECT src_norm, tgt FROM pairs WHERE direction = ?", (direction,)):
        by[src_norm].add(norm(tgt))
    return sorted((s, sorted(ts)) for s, ts in by.items() if len(ts) > 1)
