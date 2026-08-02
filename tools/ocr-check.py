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
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "lib"))
import trlib  # noqa: E402

OLLAMA = os.environ.get("TR_OLLAMA", "http://127.0.0.1:11434")
VISION_MODEL = os.environ.get("TR_VISION_MODEL", "qwen3.6:latest")
OCR_LANGS = os.environ.get("TR_OCR_LANGS", "slv+eng")

# The tokens with legal consequence. A wrong word is an edit; a wrong number
# is a different case.
NUM_RE = re.compile(r"\d[\d.,:/-]*\d|\d")
DIACRITICS = "čšžćđČŠŽĆĐ"


def render(pdf, pages, tmp):
    subprocess.run(["pdftoppm", "-png", "-r", "200", "-f", "1", "-l",
                    str(pages), pdf, os.path.join(tmp, "pg")],
                   capture_output=True, timeout=600)
    return sorted(f for f in os.listdir(tmp) if f.endswith(".png"))


def tesseract(img):
    r = subprocess.run(["tesseract", img, "stdout", "-l", OCR_LANGS],
                       capture_output=True, timeout=600)
    return r.stdout.decode("utf-8", "replace")


def vision(img):
    with open(img, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()
    body = json.dumps({
        "model": VISION_MODEL,
        "prompt": ("Transcribe all text in this document image exactly as it "
                   "appears. Preserve line breaks, diacritics, numbers and "
                   "punctuation. Output only the transcription."),
        "images": [b64], "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 8192}}).encode()
    req = urllib.request.Request(OLLAMA + "/api/generate", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        d = json.loads(r.read())
    return re.sub(r"<think>.*?</think>", "", d.get("response", ""), flags=re.S)


def nums(s):
    return {re.sub(r"\D", "", m) for m in NUM_RE.findall(s) if re.sub(r"\D", "", m)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--no-vision", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(a.pdf):
        sys.exit(f"no such file: {a.pdf}")
    out = trlib.path("work", "ocr-check")
    os.makedirs(out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.pdf))[0]

    tmp = tempfile.mkdtemp(prefix="ocrchk-")
    try:
        imgs = render(a.pdf, a.pages, tmp)
        if not imgs:
            sys.exit("could not render any page - is this a PDF?")
        print(f"  {len(imgs)} page(s) rendered at 200 dpi\n")

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

            if a.no_vision:
                print()
                continue

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
