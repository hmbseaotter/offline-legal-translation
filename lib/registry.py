"""registry.py - the single source for what the documents tabulate.

Every environment variable and every command the kit exposes is listed here
ONCE. tools/gen-docs.py writes CLAUDE.md and the operating manual from this
file; nothing in either document is maintained by hand, and the pre-commit
hook refuses a commit where they have drifted apart.

WHY

The env table said TR_PROMPT_VERSION defaulted to v1 while the code had said
v4 for weeks. Six tools existed in no document at all. Flags were added and
usage lines were not. None of that was carelessness -- it is what happens
when the same fact is written in three files and only one of them is in
front of you when you change it.

Adding a variable or a command means editing this file. The documents follow
mechanically, so they cannot disagree with it, and the only remaining
question is whether THIS file matches the code -- which gen-docs.py --check
also verifies, by reading the defaults straight out of the source.
"""

# (name, default, purpose)
ENV_VARS = [
    ('TR_PROJECTS', '~/translation-work/confidential-projects',
     'Container root holding all projects'),
    ('TR_ROOT', '(active project)',
     'Override to target one project for a single command'),
    ('TR_MODEL', 'gams3:q8',
     'Model alias used by every script'),
    ('TR_SRC / TR_TGT', 'sl / en',
     'Per-project, in project.conf. Use de for German'),
    ('TR_SUFFIX', '(empty)',
     'Per-project, in project.conf. Set if the client requires it'),
    ('TR_NUM_CTX', '8192',
     'Context window. Lower if memory is tight'),
    ('TR_PROMPT_VERSION', 'v4',
     'Part of the cache key. Bump to force retranslation'),
    ('TR_OCR_LANGS', 'slv+eng',
     'Tesseract languages. Add deu for German'),
    ('TR_OLLAMA', 'http://127.0.0.1:11434',
     'Ollama endpoint'),
    ('TR_DICTS', '/usr/share/hunspell',
     'Where tr-inventory looks for the hunspell word lists it detects language with'),
    ('TR_OCR_SAMPLE_LANGS', 'slv+hrv+eng',
     'Tesseract languages for the detection sampling pass on scanned PDFs'),
    ('TR_VENV', '~/.translate-venv',
     'Python environment the scripts re-exec into. Set before tr-setup to put it elsewhere'),
    ('TR_NO_REEXEC', '(unset)',
     'Set to 1 to stay on the system interpreter. Diagnostics only; imports will fail'),
    ('CASE_IMG', '~/.case/confidential.luks',
     'The LUKS container file. Read by case-init, case-open, case-status'),
    ('CASE_MAP', 'casedata',
     'Device-mapper name while the container is unlocked'),
    ('TR_VISION_MODEL', 'deepseek-ocr:3b',
     'Second OCR engine used by ocr-check.py. qwen3.6 is the fallback'),
    ('TR_VISION_PROMPT', 'Extract the text in the image.',
     'Prompt for that model. It transcribes; it does not follow instructions'),
    ('TR_OCR_MIN_CONF', '40',
     'Tesseract confidence floor in tr-ocrtext. Below it, a word is marked unreadable'),
    ('TR_ILLEGIBLE_MARK', 'OCR_ILLEGIBLE',
     'What tr-ocrtext writes in place of a word it could not read'),
    ('CLAUDE_DESKTOP_BIN', '/usr/bin/claude-desktop',
     'The real binary case-guard-desktop launches once it has checked the mount'),
    ('CASE_MNT', '~/translation-work/confidential-projects',
     'Where the container mounts. Also what the claude guard checks'),
]

# (invocation, purpose)
TOOLS = [
    ('`case-init` / `case-open` / `case-close` / `case-status`',
     'Encrypted container'),
    ('`tr-project [--new] <name>`',
     'List, create, or switch the active project'),
    ('`tr-setup`',
     'One-time provisioning. Idempotent.'),
    ('`tr-model`',
     'Register the GGUF with Ollama as `gams3:q8`'),
    ('`tr-fixtures [dir]`',
     'Generate synthetic test documents, including a mixed-language drop'),
    ('`tr-inventory`',
     'Classify every file in `source/` by source language. Run this before anything else'),
    ('`tr-inventory --count [--with-ocr]`',
     'Words and segments per file, to size the job before starting. Scanned PDFs need `--with-ocr`'),
    ('`tr-status`',
     'Diff `source/` against `translated/`'),
    ('`tr-run [-n] [--all] [file]`',
     'Batch translate; resumable. Without `--all`, only what the inventory matched'),
    ('`tr-docx` / `tr-xlsx` / `tr-pdf` / `tr-txt`',
     'Per-format workers. `tr-xlsx` also takes `.xlsm` / `.xltx` / `.xltm`, all delivered as `.xlsx` — the translation carries no macros and should not claim to'),
    ('`tr-lint [--tsv F] [--all-versions]`',
     'Deterministic checks over the memory. Runs no model. Scoped to the current model and prompt version unless `--all-versions`'),
    ('`tr-ocrtext <in.pdf> <out.txt>`',
     "Text layer that keeps Tesseract's per-word confidence and writes `OCR_ILLEGIBLE` below the floor. `tr-pdf` calls it instead of `pdftotext`"),
    ('`tools/ocr-check.py <f.pdf> [--pages N] [--gate PCT] [--no-vision]`',
     'Reads pages with Tesseract *and* a vision model and compares the numbers. Prints counts only, never document text. **Operator only**'),
    ('`tools/phase1-setup.sh`',
     'Prepares the Phase 1 comparison on a real subset; stops for OCR verification. **Operator only**'),
    ('`case-guard-desktop [--check]`',
     'The same refusal for the desktop app, which never consults `PATH`. Installed by `tools/install-desktop-guard.sh`'),
    ('`tools/cycle-test.sh`',
     'End-to-end run over the fixtures, no container needed'),
    ('`tools/highlight-docx.py <f.docx> [--apply]`',
     'Re-colours command blocks in the operating documents that lost their highlighting'),
    ('`tools/gen-docs.py [--apply]`',
     'Writes the tables in CLAUDE.md and the manual from lib/registry.py. '
     'Run by the pre-commit hook, which refuses a commit where they have drifted'),
]
