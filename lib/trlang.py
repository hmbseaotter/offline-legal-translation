"""Source-language detection for triage.

Client drops are not a clean Slovene corpus. They contain Slovene, English,
Croatian/Serbian, Armenian and probably more. Only the Slovene files are
translated; the rest are inventoried, counted and set aside. Sending a
Croatian file through an sl->en prompt does not merely waste a day of
inference -- it writes a cached wrong answer into work/tm.sqlite that is
silently reused forever after, so detection runs before anything else.

HOW IT DECIDES, in order:

  1. Script. Armenian and Cyrillic are settled by their Unicode block.
  2. Discriminative vocabulary. Not a character n-gram model: an earlier
     version profiled dictionary *types* and scored running-text *tokens*,
     and Slovene recall came out at 9/61. What works is asking how many of a
     text's words appear in one language's dictionary and in none of its
     rivals'.
  3. Orthography. c-acute and d-stroke are standard Croatian/Serbian and
     absent from native Slovene words, so their presence counts against
     Slovene. Their absence proves nothing.
  4. Abstention. Below MIN_TOKENS, or when the top two scores are close,
     the answer is "unknown" and a human looks at it. Guessing here is worse
     than not answering.

Croatian and Serbian are ONE class. Vocabulary does not separate them -- the
Serbian dictionary outscores the Croatian one on Croatian text, being 3.5x
larger -- and they overlap heavily in any case. markers() offers a best-effort
hint from place names and the issuing institution, which is what actually
distinguishes them on a letterhead, but nothing here depends on it.

Measured against the UDHR corpus (an independent text source; the model is
built from dictionaries, so this is not circular):

  60-word samples    152/152 correct, Slovene recall 25/25, 0 false positives
  25-word samples    357/365 correct, Slovene recall 61/61, 3 false positives

That is why MIN_TOKENS is what it is. UDHR is thin and general-register, so
treat those figures as a floor on legal text, not a guarantee.
"""
import os, re, sys

DICT_DIR = os.environ.get("TR_DICTS", "/usr/share/hunspell")

# Hunspell dictionaries. Installed by tr-setup:
#   apt install hunspell-sl hunspell-hr hunspell-sr hunspell-hy
DICT_FILES = {
    "sl":      ["sl_SI.dic"],
    "hr":      ["hr_HR.dic"],
    "sr_latn": ["sr_Latn_RS.dic"],
    "sr_cyrl": ["sr_RS.dic"],
    "hy":      ["hy_AM.dic", "hy.dic"],
    "en":      ["en_US.dic", "en_GB.dic"],
}

# What the operator sees, and what the client is told.
LABEL = {
    "sl":      "Slovene",
    "hbs":     "Croatian/Serbian",
    "en":      "English",
    "hy":      "Armenian",
    "unknown": "undetermined",
}

TARGET = "sl"                 # the only class that gets translated

MIN_TOKENS = 40               # below this, abstain rather than guess
MIN_CONFIDENCE = 0.30

ARMENIAN = re.compile(r"[԰-֏]")
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
LATINISH = re.compile(r"[A-Za-zČčŠšŽžĆćĐđ]")
CRO_SERB_ONLY = re.compile(r"[ćĆđĐ]")
_TOKEN = re.compile(r"[^\W\d_]{2,}", re.UNICODE)

# Place names and issuing institutions. A legal document says where it came
# from, usually in the header. Only ever consulted to hint at Croatian vs
# Serbian, never to decide the language itself.
MARKERS = {
    "Croatian": ["zagreb", "split", "rijeka", "osijek", "zadar", "varaždin",
                 "republika hrvatska", "županijski", "općinski sud",
                 "državno odvjetništvo", "kazneni zakon", "policijska uprava"],
    "Serbian":  ["beograd", "novi sad", "niš", "kragujevac", "subotica",
                 "republika srbija", "viši sud", "osnovni sud", "tužilaštvo",
                 "javni tužilac", "krivični zakonik", "unutrašnjih poslova"],
}


def _read_dic(path):
    """Hunspell .dic: a count on line 1, then word/FLAGS per line.

    sl_SI.aff declares no encoding, which makes hunspell assume Latin-1 while
    the file is really Latin-2 -- decode it wrongly and every Slovene word
    carrying c-caron or z-caron is corrupted, which is most of the ones that
    matter. Try UTF-8, fall back to Latin-2.
    """
    raw = open(path, "rb").read()
    for enc in ("utf-8", "iso-8859-2"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        return {ln.split("/")[0].split("\t")[0].strip().lower()
                for ln in text.split("\n")[1:] if ln.strip()}
    return set()


def tokens(text):
    return _TOKEN.findall((text or "").lower())


def script_of(text):
    a, c = len(ARMENIAN.findall(text)), len(CYRILLIC.findall(text))
    l = len(LATINISH.findall(text))
    total = a + c + l
    if total == 0:
        return "none"
    if a / total > 0.30:
        return "armenian"
    if c / total > 0.30:
        return "cyrillic"
    return "latin"


def markers(text):
    """Best-effort Croatian-vs-Serbian hint. Returns (name, hits) or (None, hits)."""
    low = (text or "").lower()
    hits = {k: sum(low.count(m) for m in ms) for k, ms in MARKERS.items()}
    top = max(hits, key=hits.get)
    if hits[top] == 0 or hits[top] == min(hits.values()):
        return None, hits
    return top, hits


class Detector:
    def __init__(self, dict_dir=None):
        self.dir = dict_dir or DICT_DIR
        self.vocab, self.missing = {}, []
        for lang, names in DICT_FILES.items():
            for n in names:
                p = os.path.join(self.dir, n)
                if os.path.exists(p):
                    self.vocab[lang] = _read_dic(p)
                    break
            else:
                self.missing.append(lang)
        sl = self.vocab.get("sl", set())
        hbs = self.vocab.get("hr", set()) | self.vocab.get("sr_latn", set())
        en = self.vocab.get("en", set())
        # What each has that the others lack. Shared words carry no signal.
        self.disc = {
            "sl":  sl - hbs - en,
            "hbs": hbs - sl - en,
            "en":  en - sl - hbs,
        }

    def ready(self):
        return not [l for l in ("sl", "hr", "sr_latn", "en") if l in self.missing]

    def why_not_ready(self):
        return ("language dictionaries missing from " + self.dir +
                " for: " + ", ".join(self.missing) +
                "\n  install: sudo apt install hunspell-sl hunspell-hr "
                "hunspell-sr hunspell-hy\n  or point TR_DICTS at a directory "
                "holding the .dic files.")

    def detect(self, text):
        """-> (lang, confidence 0..1, note). lang is a key of LABEL."""
        toks = tokens(text)
        if len(toks) < MIN_TOKENS:
            return "unknown", 0.0, f"only {len(toks)} words of text"

        script = script_of(text)
        if script == "armenian":
            return "hy", 1.0, "Armenian script"
        if script == "none":
            return "unknown", 0.0, "no alphabetic text"
        if script == "cyrillic":
            cyr = self.vocab.get("sr_cyrl", set())
            uniq = set(toks)
            rate = len(uniq & cyr) / len(uniq) if uniq else 0.0
            if rate >= 0.20:
                return "hbs", min(1.0, rate * 3), f"Cyrillic, {rate:.0%} Serbian vocabulary"
            return "unknown", 0.0, f"Cyrillic but only {rate:.0%} Serbian vocabulary"

        uniq = set(toks)
        scores = {k: (len(uniq & v) / len(uniq) if uniq else 0.0)
                  for k, v in self.disc.items()}

        note = ""
        cs = len(CRO_SERB_ONLY.findall(text))
        if cs >= 2:
            scores["sl"] *= 0.5
            note = f"c-acute/d-stroke x{cs}, not Slovene orthography"

        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        (best, bv), (_second, sv) = ranked[0], ranked[1]
        if bv <= 0:
            return "unknown", 0.0, "no discriminative vocabulary matched"

        conf = min(1.0, ((bv - sv) / bv) * 2.5)
        # Short samples were the only source of error in calibration; say so
        # in the number rather than pretending the answer is as good.
        if len(toks) < 100:
            conf *= 0.75
        if conf < MIN_CONFIDENCE:
            return "unknown", conf, f"{best} and {_second} too close to call"
        return best, conf, note or ""


_DETECTOR = None

def detector():
    global _DETECTOR
    if _DETECTOR is None:
        _DETECTOR = Detector()
    return _DETECTOR


def detect(text):
    return detector().detect(text)
