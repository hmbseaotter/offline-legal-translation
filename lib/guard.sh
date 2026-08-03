# guard.sh - the container mount rule, for the shell half of the kit.
#
#   source "$BIN/../lib/guard.sh"
#   tr_guard_resolve_root "why this script must not write outside the container"
#
# Sets and exports TR_PROJECTS and TR_ROOT. Sets PROJECTS_OVERRIDDEN.
#
# WHY THIS FILE EXISTS
#
# The rule was written out twice, in tr-run and in tr-pdf. They drifted:
# tr-pdf kept testing ${TR_PROJECTS+y} -- whether the variable was SET --
# long after tr-run and trlib had been corrected to compare resolved paths,
# and it carried a comment claiming it matched them. tr-setup exported
# TR_PROJECTS to its own default in ~/.bashrc, so "set" was true in every
# interactive shell, and the escape hatch stood permanently open on the real
# container in the one script whose output is the entire document in plain
# text.
#
# Testing that two copies agree finds that a day late. One copy cannot
# disagree with itself.
#
# THE RULE
#
# TR_PROJECTS pointing somewhere OTHER than the real container lifts the
# mount requirement -- fixtures, a mock-server run, a throwaway root. Merely
# being set does not. What matters is where the path points, not whether it
# was named. lib/trlib.py:PROJECTS_OVERRIDDEN is the same test for the
# Python half; those two are the only implementations left.
#
# The mountpoint directory exists whether or not the container is open, so
# -d says "the path is there", not "the data is encrypted". mountpoint -q is
# the test that means it.

tr_guard_resolve_root() {
  local reason="${1:-Writing there now would put case material outside the encryption.}"
  local default_projects="$HOME/translation-work/confidential-projects"

  TR_PROJECTS="${TR_PROJECTS:-$default_projects}"
  if [[ "$(readlink -f "$TR_PROJECTS")" == "$(readlink -f "$default_projects")" ]]; then
    PROJECTS_OVERRIDDEN=""
  else
    PROJECTS_OVERRIDDEN="y"
  fi

  if [[ -z "${TR_ROOT:-}" ]]; then
    if [[ -z "$PROJECTS_OVERRIDDEN" ]] && ! mountpoint -q "$TR_PROJECTS" 2>/dev/null; then
      echo "container NOT mounted: $TR_PROJECTS" >&2
      echo "$reason" >&2
      echo "  check:  case-status" >&2
      echo "  open:   case-open" >&2
      echo "  never set up:  case-init 40G" >&2
      exit 2
    fi
    # Braces around the redirect, not just 2>/dev/null on tr: when .active is
    # missing it is the SHELL that fails to open the file, and its complaint
    # is not tr's stderr. Without this the operator gets a raw
    # "No such file or directory" naming an internal path instead of the one
    # line that tells them what to do.
    #
    # `|| true` because tr-pdf runs under `set -e` while tr-run does not. A
    # failing command substitution under -e aborts the script there and then,
    # so a missing .active exited tr-pdf silently -- no message at all, which
    # is worse than the raw shell error it replaced. The guard must behave
    # the same in both, whatever each script's own error mode.
    local active
    active="$( { tr -d '[:space:]' < "$TR_PROJECTS/.active"; } 2>/dev/null )" || true
    if [[ -z "$active" ]]; then
      echo "no active project. run: tr-project <name>" >&2
      exit 2
    fi
    TR_ROOT="$TR_PROJECTS/$active"
  fi
  export TR_ROOT TR_PROJECTS
}
