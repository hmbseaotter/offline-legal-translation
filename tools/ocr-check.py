#!/usr/bin/env python3
"""ocr-check.py - is the OCR good enough to build a translation on?

OPERATOR ONLY, in a plain terminal, container open, no Claude session. This
reads real evidence.

WHY THIS EXISTS

Every source document in a prosecution bundle is a scan, so OCR is not a
risky corner of the pipeline, it is the front door. And it is the one stage
that fails silently: the model does not notice corrupted input, it produces a
fluent, confident translation of the corruption, and a misread digit in an
amount reads as correct all the way to the deliverable.

Phase 1 costs the translator an hour of real work. If the OCR underneath is
poor, that hour measures Tesseract rather than the translation, and the ratio
answers a question nobody asked. Two pages settle it beforehand.

WHAT IT DOES

Reads the same pages twice, by two mechanisms that fail differently:
Tesseract, which recognises glyph shapes, and the vision model, which reads
the page the way a reader does. Where they agree, the text is probably right.
Where they disagree on a NUMBER, one of them is wrong and it matters -- case
numbers, dates and amounts are the tokens with legal consequence.

WHAT IT PRINTS

Counts and rates. Never document text. The transcriptions are written inside
the container for you to read locally; only the statistics are safe to paste
into a chat.

USAGE

  ocr-check.py <file.pdf> [--pages 2] [--no-vision]

Vision costs about 6.7 minutes a page and Tesseract seconds, so two pages is
roughly a quarter of an hour. --no-vision gives the Tesseract-only view in
seconds, which is enough to spot catastrophic OCR.
"""
import argparse
import base64
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "lib"))
import trlib  # noqa: E402

OLLAMA = os.environ.get("TR_OLLAMA", "http://127.0.0.1:11434")
# deepseek-ocr:3b, not the 36B general model. Measured on the same A4 page of
# Slovene legal text at 200 dpi: 88 seconds against 2,855 on a real page with
# qwen3.6 -- roughly thirty times faster -- with all 38 diacritics and all 26
# numbers correct and 100% agreement with Tesseract. A model built for reading
# documents beats a much larger one asked to read a document as a favour.
#
# TR_VISION_MODEL overrides it. qwen3.6 remains the fallback worth trying on a
# page deepseek cannot make sense of, since their failure modes differ.
VISION_MODEL = os.environ.get("TR_VISION_MODEL", "deepseek-ocr:3b")
OCR_LANGS = os.environ.get("TR_OCR_LANGS", "slv+eng")

# The tokens with legal consequence. A wrong word is an edit; a wrong number
# is a different case.
NUM_RE = re.compile(r"\d[\d.,:/-]*\d|\d")
DIACRITICS = "čšžćđČŠŽĆĐ"

PROMPT_FULL = ("Transcribe all text in this document image exactly as it "
               "appears. Preserve line breaks, diacritics, numbers and "
               "punctuation. Output only the transcription.")

# The cheap question. Only number disagreements are acted on, and generation
# is what the wall clock is made of: a real page produced ~500 words of
# transcription in 45 minutes on the 36B model, where its numbers alone would
# have been a tenth of that. Asking for the whole page in order to compare a
# fiftieth of it was the wrong trade.
PROMPT_NUMBERS = ("List every number visible in this document image - dates, "
                  "case numbers, reference numbers, amounts, quantities, "
                  "percentages. One per line, exactly as printed, including "
                  "any punctuation inside the number. No other text, no "
                  "commentary, no headings.")

NUMBERS_ONLY = True     # cleared by --full


def render(pdf, pages, tmp):
    subprocess.run(["pdftoppm", "-png", "-r", "200", "-f", "1", "-l",
                    str(pages), pdf, os.path.join(tmp, "pg")],
                   capture_output=True, timeout=600)
    return sorted(f for f in os.listdir(tmp) if f.endswith(".png"))


def tesseract(img):
    r = subprocess.run(["tesseract", img, "stdout", "-l", OCR_LANGS],
                       capture_output=True, timeout=600)
    return r.stdout.decode("utf-8", "replace")


def tesseract_conf(img):
    """Per-word confidence, and what it does and does not tell you.

    Forms in an evidence bundle are filled in by hand, and handwriting does
    not fail loudly: Tesseract emits plausible-looking words rather than
    nothing, and the model then translates them fluently. Confidence catches
    that case well -- scrawl scores in the tens where print scores in the
    high eighties.

    What it does NOT catch is a misread digit in clean print. A test page
    reading "12.450,00 EUR" came back as 1248000 at 86% confidence: a wrong
    amount, asserted as firmly as a right one. So a confidence floor finds
    handwriting, and only a second engine reading the same page finds that.
    """
    r = subprocess.run(["tesseract", img, "stdout", "-l", OCR_LANGS, "tsv"],
                       capture_output=True, timeout=600)
    words = []
    for ln in r.stdout.decode("utf-8", "replace").splitlines()[1:]:
        c = ln.split("\t")
        if len(c) >= 12 and c[11].strip() and c[10] not in ("-1", "conf"):
            try:
                words.append((float(c[10]), c[11]))
            except ValueError:
                pass
    return words


def vision(img):
    """Stream, so the wait is visible.

    Run without streaming this sat silent for twenty-two minutes: several
    minutes evicting the translation model and loading a 23 GB one, then
    seven of inference, with nothing on the terminal to distinguish work from
    a hang. A heartbeat during the load and a token count during generation
    cost nothing and answer the only question the operator has.

    The counter prints how many tokens have arrived, never what they say. The
    page is evidence.
    """
    with open(img, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()
    body = json.dumps({
        "model": VISION_MODEL,
        "prompt": PROMPT_NUMBERS if NUMBERS_ONLY else PROMPT_FULL,
        "images": [b64], "stream": True,
        "options": {"temperature": 0.1, "num_ctx": 8192}}).encode()
    req = urllib.request.Request(OLLAMA + "/api/generate", body,
                                 {"Content-Type": "application/json"})

    started = time.time()
    first = threading.Event()

    def waiting():
        while not first.wait(30):
            sys.stdout.write(f"\r                loading / prefilling, "
                             f"{time.time() - started:.0f}s elapsed   ")
            sys.stdout.flush()

    t = threading.Thread(target=waiting, daemon=True)
    t.start()
    parts, n = [], 0
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            for line in r:
                if not line.strip():
                    continue
                d = json.loads(line)
                if not first.is_set():
                    first.set()
                    sys.stdout.write(f"\r                first token after "
                                     f"{time.time() - started:.0f}s, reading   ")
                parts.append(d.get("response", ""))
                n += 1
                if n % 20 == 0:
                    sys.stdout.write(f"\r                {n} tokens, "
                                     f"{time.time() - started:.0f}s        ")
                    sys.stdout.flush()
                if d.get("done"):
                    break
    finally:
        first.set()
        sys.stdout.write("\r" + " " * 70 + "\r")
        sys.stdout.flush()
    return re.sub(r"<think>.*?</think>", "", "".join(parts), flags=re.S)


def nums(s):
    return {re.sub(r"\D", "", m) for m in NUM_RE.findall(s) if re.sub(r"\D", "", m)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--no-vision", action="store_true")
    ap.add_argument("--full", action="store_true",
                    help="ask the vision model for the whole page rather than "
                         "just its numbers. Far slower; only number "
                         "disagreements are acted on")
    ap.add_argument("--gate", type=float, default=6.0,
                    help="skip the vision pass where fewer than this percent "
                         "of Tesseract words were doubtful (default 6). "
                         "0 disables the gate")
    a = ap.parse_args()
    global NUMBERS_ONLY
    NUMBERS_ONLY = not a.full

    if not os.path.isfile(a.pdf):
        sys.exit(f"no such file: {a.pdf}")
    out = trlib.path("work", "ocr-check")
    os.makedirs(out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.pdf))[0]

    if not a.no_vision:
        have = subprocess.run(["ollama", "list"], capture_output=True,
                              timeout=60).stdout.decode("utf-8", "replace")
        if VISION_MODEL.split(":")[0] not in have:
            sys.exit(f"vision model {VISION_MODEL} is not registered.\n"
                     f"Either pull it or run with --no-vision.")
        print(f"  Tesseract runs in seconds. The vision pass with "
              f"{VISION_MODEL}")
        print(f"  takes roughly 1.5 minutes a page once loaded, and only runs "
              f"where")
        print(f"  Tesseract was unsure (--gate {a.gate:.0f}%). --no-vision "
              f"skips it entirely.\n")

    tmp = tempfile.mkdtemp(prefix="ocrchk-")
    try:
        imgs = render(a.pdf, a.pages, tmp)
        if not imgs:
            sys.exit("could not render any page - is this a PDF?")
        print(f"  {len(imgs)} page(s) rendered at 200 dpi\n")

        gated = 0
        for n, img in enumerate(imgs, 1):
            p = os.path.join(tmp, img)
            t0 = time.time()
            t_txt = tesseract(p)
            t_secs = time.time() - t0
            open(os.path.join(out, f"{stem}-p{n}-tesseract.txt"), "w",
                 encoding="utf-8").write(t_txt)

            tw = len(t_txt.split())
            td = sum(t_txt.count(c) for c in DIACRITICS)
            print(f"  page {n}")
            print(f"    tesseract   {tw:>5} words  {len(nums(t_txt)):>4} numbers"
                  f"  {td:>4} diacritics   {t_secs:>5.0f}s")

            conf = tesseract_conf(p)
            if conf:
                low = [(c, w) for c, w in conf if c < 40]
                doubt = [(c, w) for c, w in conf if 40 <= c < 60]
                lownum = [(c, w) for c, w in low if any(ch.isdigit() for ch in w)]
                pct = 100.0 * len(low) / len(conf)
                print(f"    confidence  {len(low)} of {len(conf)} words below 40"
                      f" ({pct:.0f}%), {len(doubt)} between 40 and 60")
                if pct >= 20:
                    print(f"                ^ a fifth of the page is unreadable to"
                          f" Tesseract. Handwriting looks")
                    print(f"                  exactly like this. Those lines need"
                          f" a person, not a better model.")
                if lownum:
                    print(f"                {len(lownum)} unreadable token(s)"
                          f" contain digits - a hand-filled date or amount")
                    print(f"                  is the worst thing to guess at."
                          f" Mark them [ILLEGIBLE] rather than translate them.")

            if a.no_vision:
                print()
                continue

            # The gate. Page 2 of a real document had 4% of its words doubtful
            # and agreed with the vision model on all 29 numbers; page 1 had
            # 9% doubtful and disagreed on 17. Tesseract's own confidence
            # predicted which page needed a second opinion before any second
            # opinion was taken -- so spend the expensive pass where the cheap
            # one is unsure, not everywhere.
            if a.gate > 0 and conf and pct < a.gate:
                print(f"    vision      skipped: {pct:.0f}% doubtful is below "
                      f"the {a.gate:.0f}% gate")
                print(f"                Tesseract is confident here. --gate 0 "
                      f"to check anyway.")
                gated += 1
                print()
                continue

            # Say this before the wait, not after. The vision model is 23 GB
            # against gams3's 13 on a 30 GB machine, so the first call evicts
            # the translation model and loads this one before any inference
            # starts -- several minutes of complete silence, which reads as a
            # hang rather than as work.
            if n == 1:
                print(f"    vision      loading {VISION_MODEL}, then reading "
                      f"page 1.", flush=True)
                print(f"                The first page includes the model "
                      f"load.", flush=True)
            else:
                print(f"    vision      reading page {n}, about 7 minutes.",
                      flush=True)
            t0 = time.time()
            try:
                v_txt = vision(p)
            except Exception as e:
                print(f"    vision      FAILED: {type(e).__name__}\n")
                continue
            v_secs = time.time() - t0
            open(os.path.join(out, f"{stem}-p{n}-vision.txt"), "w",
                 encoding="utf-8").write(v_txt)

            vw = len(v_txt.split())
            vd = sum(v_txt.count(c) for c in DIACRITICS)
            print(f"    vision      {vw:>5} words  {len(nums(v_txt)):>4} numbers"
                  f"  {vd:>4} diacritics   {v_secs:>5.0f}s")

            tn, vn = nums(t_txt), nums(v_txt)
            both, only_t, only_v = tn & vn, tn - vn, vn - tn
            sim = difflib.SequenceMatcher(
                None, re.sub(r"\s+", " ", t_txt).strip().lower(),
                re.sub(r"\s+", " ", v_txt).strip().lower()).ratio()
            print(f"    agreement   {sim:.0%} of the text")
            print(f"    numbers     {len(both)} agreed, "
                  f"{len(only_t)} only tesseract, {len(only_v)} only vision")
            if only_t or only_v:
                print(f"                ^ every one of these is a number one "
                      f"engine read and the other did not.")
                print(f"                  Check them against the page. They are "
                      f"case numbers, dates and amounts.")
            print()
    finally:
        subprocess.run(["rm", "-rf", tmp], capture_output=True)

    if gated:
        print(f"  {gated} of {len(imgs)} page(s) skipped the vision pass: "
              f"Tesseract was confident.")
        print(f"  On a corpus this is where the time is saved - the "
              f"expensive read runs only")
        print(f"  where the cheap one is unsure.\n")
    print(f"  transcriptions written to {out}")
    print("  Read them against the page images. What matters is not the word")
    print("  count but whether the numbers, names and diacritics are right.")
    print()
    print("  If Tesseract alone is clean, Phase 1 can proceed on it.")
    print("  If the two engines disagree on numbers, the cross-check is")
    print("  earning its cost and belongs in the pipeline before bulk work.")
    print("  If both are poor, the fix is upstream: rescan, or better source")
    print("  copies from the prosecution.")


if __name__ == "__main__":
    main()
