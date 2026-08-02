#!/usr/bin/env bash
# phase1-setup.sh - prepare the Phase 1 comparison on a real subset.
#
# OPERATOR ONLY, in a plain terminal, with the container open and no Claude
# session running. This touches real case material.
#
# Phase 1 answers one question: does machine assistance make the translator
# faster? The ratio is minutes per page edited against minutes per page
# translated from scratch. At or above 1.0 the answer is no and the project
# stops.
#
# WHAT YOU PREPARE BEFORE RUNNING THIS
#
#   <project>/source/phase1/mt/        3 pages to be machine-drafted
#   <project>/source/phase1/scratch/   3 comparable pages, NOT drafted
#
# The two sets must not share content. If the same passages appear in both,
# whichever set is done second is faster because the translator has already
# read them, and the ratio measures that instead of the tooling. Same
# document type and similar density; different documents.
#
# WHAT THIS SCRIPT DOES
#
#   1. Pre-flight: model, dictionaries, venv, container, no assistant
#   2. Triage, so a non-Slovene page does not end up in the comparison
#   3. Volume count, giving the source-word baseline billing rests on
#   4. Drafts the mt/ set ONLY, and never touches scratch/
#   5. Lints the drafts
#   6. Writes a bilingual copy of each draft for side-by-side review
#   7. Lays out the tally sheet
#
# It prints counts, paths and status lines. It does not print document text.

set -uo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$KIT/bin:$PATH"
fail=0
step() { printf '\n=== %s\n' "$1"; }
ok()   { printf '  ok    %s\n' "$1"; }
bad()  { printf '  STOP  %s\n' "$1"; fail=1; }

step "1. pre-flight"
pgrep -x claude >/dev/null 2>&1 && bad "a Claude session is running - close it" \
                                || ok "no assistant session"
case-status >/dev/null 2>&1 || true
MNT="${CASE_MNT:-$HOME/translation-work/confidential-projects}"
mountpoint -q "$MNT" && ok "container open" || bad "container not open - case-open"
ollama list 2>/dev/null | grep -q "^gams3:q8" && ok "model registered" \
                                              || bad "gams3:q8 missing - tr-model"
[ -d "$HOME/.translate-venv" ] && ok "venv present" || bad "no venv - tr-setup"
ls /usr/share/hunspell/sl_SI.dic >/dev/null 2>&1 && ok "dictionaries present" \
                                                 || bad "hunspell dicts missing - tr-setup"
(( fail )) && { echo; echo "Fix the above, then re-run."; exit 1; }

ROOT="$(tr-project 2>/dev/null | awk '/^active:/{print $2}')"
SRC="$MNT/${ROOT:-}/source"
[ -d "$SRC/phase1/mt" ] || { echo "  STOP  no $SRC/phase1/mt"; exit 1; }
[ -d "$SRC/phase1/scratch" ] || { echo "  STOP  no $SRC/phase1/scratch"; exit 1; }
nmt=$(find "$SRC/phase1/mt" -type f | wc -l)
nsc=$(find "$SRC/phase1/scratch" -type f | wc -l)
ok "mt set: $nmt file(s), scratch set: $nsc file(s)"
[ "$nmt" -gt 0 ] || { echo "  STOP  mt set is empty"; exit 1; }

step "2. triage - is everything actually in the source language?"
tr-inventory
echo
echo "  If anything in phase1/ came back as another language, take it out of"
echo "  the comparison. A held-back file is not billable work and would not"
echo "  have been translated anyway."

step "3. volume - the source-word baseline"
tr-inventory --count
echo
echo "  Source words is the billing unit. Note the figure for the six pages;"
echo "  the ratio is per page, but the quote is per word."

step "4. draft the mt set (scratch/ is not touched)"
mapfile -t MTFILES < <(find "$SRC/phase1/mt" -type f | sort)
printf '  drafting %d file(s) at roughly 48 s a segment\n' "${#MTFILES[@]}"
tr-run "${MTFILES[@]}"

step "5. lint the drafts"
tr-lint

step "6. bilingual copies for side-by-side review"
OUT="$MNT/${ROOT}/work/phase1-review"
mkdir -p "$OUT"
for f in "${MTFILES[@]}"; do
  b="$(basename "${f%.*}")"
  case "${f##*.}" in
    txt) tr-txt "$f" "$OUT/$b.bilingual.docx" --bilingual >/dev/null 2>&1 \
         && ok "bilingual: $b.bilingual.docx" ;;
    *)   ok "$b: edit the draft in translated/ directly" ;;
  esac
done

step "7. the tally sheet"
TALLY="$MNT/${ROOT}/work/phase1-tally.tsv"
if [ ! -f "$TALLY" ]; then
  cp "$KIT/tools/phase1-tally.tsv" "$TALLY" 2>/dev/null && ok "created $TALLY" \
    || bad "could not create the tally sheet"
else
  ok "tally sheet already exists, left alone"
fi

cat <<EOF

========================================================================
Ready. What happens next is the translator's, not the machine's.

  1. Time three pages from scratch/ translated cold, minutes per page.
  2. Time three pages from mt/ edited from the draft, minutes per page.
     Alternate the order between pages rather than doing all of one set
     then all of the other -- fatigue and warm-up both bias a small sample.
  3. For every edit made to a draft, add a tick in the tally sheet under
     the class it belongs to.

  ratio = minutes per page edited / minutes per page from scratch
  At or above 1.0, machine assistance is not paying for itself.

  tally: $TALLY
  drafts: $MNT/${ROOT}/translated/phase1/mt/

Take back to the design conversation: the ratio, the per-class counts, and
the source-word total. Not the text.
========================================================================
EOF
