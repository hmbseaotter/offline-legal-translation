#!/usr/bin/env bash
# Render the architecture report in all three editions (Short, Medium, Long),
# each as DOCX and PDF.
#
#   docs/architecture/render/render.sh [output-dir]     (default: docs/architecture/dist)
#
# Needs: Node.js, Graphviz (`dot`), LibreOffice with its Python bridge
# (`python3 -c "import uno"`), and the `docx` npm package, which this script
# installs into render/node_modules on first use if Node cannot already find it.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
docs="$(dirname "$here")"
out="${1:-$docs/dist}"
mkdir -p "$out" "$out/.raw"

for tool in node dot soffice python3 pdfinfo; do
  command -v "$tool" >/dev/null || { echo "missing prerequisite: $tool" >&2; exit 1; }
done
python3 -c "import uno" 2>/dev/null || { echo "missing prerequisite: LibreOffice Python bridge (uno)" >&2; exit 1; }
if ! (cd "$here" && node -e "require('docx')" 2>/dev/null); then
  echo "installing docx@9.8.1 into $here/node_modules"
  (cd "$here" && npm install --no-save --no-package-lock --silent docx@9.8.1)
fi

name="$(sed -n 's/^short_title:[[:space:]]*//p' "$docs/source.md" | head -n 1)"
for tier in S M L; do
  case "$tier" in S) edition=Short ;; M) edition=Medium ;; L) edition=Long ;; esac
  base="${name}_Report_${edition}"
  (cd "$here" && node build.js "$docs/source.md" "$tier" "$out/.raw/$base.docx" >/dev/null)
  python3 "$here/finalize.py" "$out/.raw/$base.docx" "$out/$base.docx" "$out/$base.pdf"
  printf '%-48s %3s pages\n' "$base" "$(pdfinfo "$out/$base.pdf" | awk '/^Pages/{print $2}')"
done
rm -r "$out/.raw"
