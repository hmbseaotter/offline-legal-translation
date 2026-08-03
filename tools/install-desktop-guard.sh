#!/usr/bin/env bash
# install-desktop-guard.sh - route the desktop launcher through case-guard.
#
# The launcher reads .desktop files, not PATH, so shadowing `claude` on PATH
# never touched it. A user .desktop file shadows the system one of the same
# filename, which is the supported way to change how an application starts
# without editing anything the package manager owns -- and without the change
# being undone by the next update.
#
# Idempotent. Re-run after a Claude update if the system entry changes.

set -uo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYS=/usr/share/applications/com.anthropic.Claude.desktop
USR="$HOME/.local/share/applications/com.anthropic.Claude.desktop"
GUARD="$HOME/.local/sbin/case-guard-desktop"

[[ -f "$SYS" ]] || { echo "system entry not found: $SYS" >&2; exit 1; }

mkdir -p "$HOME/.local/sbin" "$HOME/.local/share/applications"
install -m 755 "$KIT/bin/case-guard-desktop" "$GUARD"
echo "  guard installed: $GUARD"

# Rewrite every Exec= to go through the guard. The file has several: the main
# entry and the "New chat" / "New Claude Code session" actions. Every one of
# them starts the application, so every one has to be covered -- guarding only
# the first would leave the dock's right-click menu as an open door.
sed -E 's#^Exec=(/usr/bin/)?claude-desktop#Exec='"$GUARD"'#' "$SYS" > "$USR"
chmod 644 "$USR"

n=$(grep -c "^Exec=$GUARD" "$USR")
t=$(grep -c "^Exec=" "$USR")
echo "  override written: $USR"
echo "  $n of $t Exec lines routed through the guard"
[[ "$n" == "$t" ]] || echo "  WARNING: some Exec lines were not rewritten - check by hand"

command -v update-desktop-database >/dev/null 2>&1 && \
  update-desktop-database "$HOME/.local/share/applications" 2>/dev/null

cat <<EOF

  Done. The launcher, the dock and the claude:// URI handler now go through
  the guard, which refuses while the container is mounted and shows a dialog
  saying so -- there is no terminal behind a GUI launch to print to.

  Test it: open the container, then start Claude from the launcher. It should
  refuse. Then case-close and try again.

  To undo:  rm "$USR"
EOF
