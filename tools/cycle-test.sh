#!/usr/bin/env bash
# cycle-test.sh - exercise a full container cycle with a throwaway project.
#
# OPERATOR ONLY, in a plain terminal. case-open refuses while a claude
# process is running, by design: assistant sessions and case data must never
# be present at once. Exit Claude Code before running this.
#
# Everything it puts in the container is synthetic -- tr-fixtures output,
# invented Slovene legal text. It prints counts, paths and status lines and
# never the contents of a file, so the output is safe to paste back into a
# session or a chat.
#
# Removes its own project at the end and closes the container.

set -uo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$KIT/bin:$PATH"
PROJ="cycle-test"
MNT="${CASE_MNT:-$HOME/translation-work/confidential-projects}"
fail=0

step() { printf '\n=== %s\n' "$1"; }
ok()   { printf '  ok    %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; fail=1; }
check(){ if eval "$1"; then ok "$2"; else bad "$2"; fi; }

# PRECONDITION, not a test.
#
# This exercises the closed -> open -> closed transition, so it has to start
# from closed; there is no way to establish the "before" baseline otherwise.
# That was previously written as three check calls, which meant an operator
# who already had the container open got three FAIL lines, the whole suite
# ran anyway, every functional check passed, and the run still ended in
# CYCLE FAILED. The verdict blamed the system for the operator's starting
# state, twice, and the second time cost a full read of the output to
# discover nothing was actually broken.
#
# It also has to refuse rather than close the container itself. Step 6 closes
# what step 1 opened; if the container was already open, that unmounts a
# session this script did not start and may have real work in it. Closing
# someone else's container is not a decision a test gets to make.
if mountpoint -q "$MNT" 2>/dev/null; then
  cat >&2 <<EOF

  The container is open, and this test needs to start from closed - it
  exercises the whole open/close cycle and cannot check the closed state
  otherwise.

  It will not close the container for you: it did not open it, and it has
  no way to tell an idle mount from one with a batch running in it.

    case-close      then run this again

EOF
  exit 2
fi

step "0. before: container is closed and the mountpoint immutable"
case-status
check '! mountpoint -q "$MNT"' "not mounted"
check 'lsattr -d "$MNT" 2>/dev/null | cut -c5 | grep -q i' "mountpoint immutable"
check '[ -z "$(ls -A "$MNT" 2>/dev/null)" ]' "mountpoint empty"

step "1. open"
case-open || { echo "case-open failed - stopping"; exit 1; }
check 'mountpoint -q "$MNT"' "mounted"
check 'lsattr -d "$MNT" 2>/dev/null | cut -c5 | grep -qv i' "immutable lifted while open"
check '[ -d "$MNT/_shared/glossary" ]' "_shared seeded by case-init"
echo "  _shared contents: $(find "$MNT/_shared" -type f | wc -l) file(s)"

step "2. create a project"
# tr-project --new switches .active to the new project, and step 5 used to
# delete .active outright. An operator with a real matter selected would
# find no active project afterwards and no sign of what had changed it, so
# remember what was there and put it back.
PREV_ACTIVE="$(cat "$MNT/.active" 2>/dev/null || true)"
[ -n "$PREV_ACTIVE" ] && echo "  active project before this run: $PREV_ACTIVE"
tr-project --new "$PROJ" >/dev/null 2>&1
check '[ -d "$MNT/$PROJ/source" ]' "project scaffolded"
check '[ "$(cat "$MNT/.active" 2>/dev/null)" = "$PROJ" ]' ".active records it"

step "3. put synthetic fixtures in source/"
tr-fixtures /tmp/cycle-fx >/dev/null 2>&1
cp -a /tmp/cycle-fx/drop/. "$MNT/$PROJ/source/" 2>/dev/null
echo "  files placed: $(find "$MNT/$PROJ/source" -type f | wc -l)"
check '[ "$(find "$MNT/$PROJ/source" -type f | wc -l)" -gt 0 ]' "source populated"

step "4. the tools work against a real mounted project"
tr-status 2>&1 | sed 's/^/  /'
check 'tr-status >/dev/null 2>&1' "tr-status runs"
tr-inventory 2>&1 | grep -vE "^  [0-9]+/" | sed 's/^/  /'
check '[ -f "$MNT/$PROJ/work/inventory/manifest.tsv" ]' "inventory written"

step "5. tear the project down"
rm -rf "${MNT:?}/$PROJ"
if [ -n "$PREV_ACTIVE" ]; then
  printf '%s\n' "$PREV_ACTIVE" > "$MNT/.active"
  echo "  active project restored: $PREV_ACTIVE"
else
  rm -f "$MNT/.active"
fi
rm -rf /tmp/cycle-fx
check '[ ! -d "$MNT/$PROJ" ]' "project removed"
check '[ "$(cat "$MNT/.active" 2>/dev/null || true)" = "$PREV_ACTIVE" ]' \
      "active project left as found"

step "6. close"
case-close || { echo "case-close failed"; exit 1; }
check '! mountpoint -q "$MNT"' "unmounted"
check 'lsattr -d "$MNT" 2>/dev/null | cut -c5 | grep -q i' "immutable restored"
check '[ -z "$(ls -A "$MNT" 2>/dev/null)" ]' "mountpoint empty again"

step "7. after: the tools refuse again"
tr-run -n 2>&1 | head -2 | sed 's/^/  /'
check '! tr-run -n >/dev/null 2>&1' "tr-run refuses while closed"
case-status

printf '\n%s\n' "$([ $fail -eq 0 ] && echo 'CYCLE PASSED' || echo 'CYCLE FAILED - see FAIL lines above')"
exit $fail
