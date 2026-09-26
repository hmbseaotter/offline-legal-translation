# conf.sh - per-project settings, for the shell half of the kit.
#
#   source "$BIN/../lib/conf.sh"
#   tr_load_conf "$TR_ROOT/project.conf"
#
# Exports what the file names and the environment has not already set.
#
# WHY THIS FILE EXISTS
#
# tr-run defined this parse inside itself, so tr-run was the only shell tool
# that had it. tr-pdf took its OCR languages from the environment alone,
# while the tr-ocrtext it calls reads project.conf through trlib -- so one
# hand-run told ocrmypdf slv+eng and wrote the text layer beside it in the
# project's own languages. Two halves of one command, disagreeing about the
# project they were run in.
#
# Parsed rather than sourced. project.conf is data, and sourcing it both
# executes whatever it contains and clobbers the environment -- so
# `TR_SUFFIX=x tr-run` was silently overridden by the file. An explicit
# environment setting is a deliberate one-off and wins.
#
# lib/trlib.py:_load_project_conf() reads the same file by the same rules for
# the Python half. Those two are the only implementations, one per language.

tr_load_conf() {
  local f="$1" line k v
  [[ -f "$f" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    [[ "$line" == *=* ]] || continue
    k="${line%%=*}"; v="${line#*=}"
    read -r k <<< "$k" || true                 # trims surrounding whitespace
    read -r v <<< "$v" || true
    [[ "$k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
    [[ -n "${!k+set}" ]] || export "$k=$v"
  done < "$f"
  # tr-pdf runs under `set -e` and tr-run does not, as guard.sh found before
  # this file existed: a loop whose last line was a comment ends on a false
  # test, and that would abort the caller here rather than return.
  return 0
}
