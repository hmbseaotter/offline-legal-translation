#!/usr/bin/env python3
"""calibrate_lang.py - measure trlang detection accuracy at a given sample length.

Usage:  calibrate_lang.py <corpus-dir> [--lengths 25,40,60,100] [--stride N]

<corpus-dir> holds one subdirectory per language. --lengths sets the sample
sizes in words to test; --stride steps through each text rather than
sampling only its start.

The accuracy figures quoted in lib/trlang.py came from a run of this kind
against UDHR text. The samples themselves are not in this repository -- they
are third-party text, and the repository holds no corpora -- so the numbers
in that docstring record a measurement rather than something the repo can
re-derive unaided. This harness is what makes them checkable again: point it
at a labelled sample set and it re-measures.

Run it after ANY change to scoring, MIN_TOKENS, the dictionary set, or the
orthography rules. A detector that silently gets worse is the failure this
project can least afford: a wrong language label sends the file through the
wrong prompt and caches the wrong answer in work/tm.sqlite, where it is
reused without complaint.

USAGE

  calibrate_lang.py <corpus-dir> [--lengths 25,40,60,100] [--stride N]

The corpus directory is labelled by layout -- one subdirectory per language,
named with the key trlang uses:

    corpus/
      sl/*.txt        Slovene
      hbs/*.txt       Croatian or Serbian (one class; see trlang)
      en/*.txt        English
      hy/*.txt        Armenian

Every file is cut into consecutive non-overlapping samples of each requested
length, each sample is classified, and the result is compared to the
directory it came from. "unknown" is never counted as correct: abstention is
reported separately, because abstaining is a different act from being wrong
and the two must not be averaged together.

WHAT TO LOOK AT

False positives matter more than raw accuracy here. Calling a Croatian file
Slovene is the expensive error -- it gets translated, wrongly, and poisons
the memory. Calling a Slovene file Croatian is cheap: it lands in the
held-back pile and a human sees it. The report separates the two.
"""
import os
import sys
import argparse
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import trlang


def samples(text, n, stride=None):
    """Consecutive n-word samples. stride defaults to n (no overlap)."""
    words = text.split()
    step = stride or n
    for i in range(0, max(0, len(words) - n + 1), step):
        yield " ".join(words[i:i + n])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", help="directory with one subdirectory per language")
    ap.add_argument("--lengths", default="25,40,60,100",
                    help="comma-separated sample lengths in words")
    ap.add_argument("--stride", type=int, default=0,
                    help="word step between samples (default: no overlap)")
    a = ap.parse_args()

    det = trlang.detector()
    if not det.ready():
        sys.exit("\n" + det.why_not_ready() + "\n")

    langs = sorted(d for d in os.listdir(a.corpus)
                   if os.path.isdir(os.path.join(a.corpus, d)))
    if not langs:
        sys.exit(f"no language subdirectories in {a.corpus}")

    print(f"MIN_TOKENS currently {trlang.MIN_TOKENS}; "
          f"samples shorter than that abstain by construction.\n")

    for n in [int(x) for x in a.lengths.split(",")]:
        correct = wrong = abstained = 0
        confusion = defaultdict(Counter)
        for lang in langs:
            d = os.path.join(a.corpus, lang)
            for fn in sorted(os.listdir(d)):
                p = os.path.join(d, fn)
                if not os.path.isfile(p):
                    continue
                with open(p, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                for s in samples(text, n, a.stride or None):
                    got, _conf, _note = det.detect(s)
                    confusion[lang][got] += 1
                    if got == "unknown":
                        abstained += 1
                    elif got == lang:
                        correct += 1
                    else:
                        wrong += 1

        total = correct + wrong + abstained
        if not total:
            print(f"{n:>4}-word samples: none produced")
            continue

        # The expensive error, called out on its own.
        fp_target = sum(c[trlang.TARGET] for l, c in confusion.items()
                        if l != trlang.TARGET)
        recall = confusion.get(trlang.TARGET, Counter())
        tgt_total = sum(recall.values())

        print(f"{n:>4}-word samples: {correct}/{correct + wrong} correct "
              f"of those answered, {abstained} abstained, {total} total")
        print(f"      {trlang.TARGET} recall "
              f"{recall.get(trlang.TARGET, 0)}/{tgt_total}"
              f"   false '{trlang.TARGET}' (the costly error): {fp_target}")
        for lang in langs:
            row = ", ".join(f"{k}={v}" for k, v in confusion[lang].most_common())
            print(f"        {lang:<8} -> {row}")
        print()


if __name__ == "__main__":
    main()
