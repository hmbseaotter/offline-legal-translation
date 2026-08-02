"""Shared helpers for the offline translation pipeline.

Nothing here talks to the network except ollama_translate(), which speaks
only to http://127.0.0.1:11434 (the local Ollama daemon).
"""
import os, re, json, sqlite3, hashlib, urllib.request, sys, time

# ------------------------------------------------------------ interpreter

# tr-setup installs python-docx and openpyxl into a venv, but every entry
# script is `#!/usr/bin/env python3` and so starts under the *system*
# interpreter, where those imports fail. Re-exec under the venv interpreter
# so the shebang and the dependencies agree.
#
# Every script that needs those packages imports trlib before importing
# them, so doing this at trlib import time is early enough. Set
# TR_NO_REEXEC=1 to disable.

def _reexec_in_venv():
    venv = os.environ.get("TR_VENV", os.path.expanduser("~/.translate-venv"))
    # Already inside it? sys.prefix is the venv when running under one.
    # (Comparing interpreter paths does not work: a venv's python3 is a
    # symlink to the system binary, so realpath makes them identical.)
    if os.path.realpath(sys.prefix) == os.path.realpath(venv):
        return
    py = os.path.join(venv, "bin", "python3")
    if not os.path.exists(py):
        py = os.path.join(venv, "bin", "python")
    if not os.path.exists(py):
        return                      # no venv yet: let the import fail loudly
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if not script or not os.path.isfile(script):
        return                      # `python3 -c ...` or a REPL: leave alone
    os.execv(py, [py, script] + sys.argv[1:])

if os.environ.get("TR_NO_REEXEC") != "1":
    _reexec_in_venv()

# ---------------------------------------------------------------- project

# All confidential projects live under one root, which is where the
# encrypted container mounts. Each project is a directory beneath it.
PROJECTS = os.environ.get(
    "TR_PROJECTS",
    os.path.expanduser("~/translation-work/confidential-projects"))
SHARED = os.path.join(PROJECTS, "_shared")

DEFAULT_PROJECTS = os.path.expanduser("~/translation-work/confidential-projects")

# Pointing TR_PROJECTS somewhere ELSE is the deliberate act -- fixtures, a
# mock-server run, a throwaway root -- and that is what lifts the mount
# requirement below.
#
# Deliberately not `"TR_PROJECTS" in os.environ`. tr-setup exports the
# variable to its own default value in ~/.bashrc, which changes nothing
# functionally but made the variable *set* in every interactive shell -- so
# the escape hatch stood permanently open on the real container and every
# tool would have written plaintext onto an unmounted mountpoint without a
# word. What matters is where the path points, not whether it was named.
PROJECTS_OVERRIDDEN = os.path.realpath(PROJECTS) != os.path.realpath(DEFAULT_PROJECTS)

def _under(child, parent):
    p = os.path.realpath(parent)
    return os.path.realpath(child) == p or os.path.realpath(child).startswith(p + os.sep)

def container_mounted():
    """Is the encrypted container actually open?

    The mountpoint directory exists whether or not anything is mounted on it
    -- when the container is closed it is simply an empty directory, and if
    case-init has never run it is a plain directory like any other. So
    os.path.isdir() answers "does the path exist", not "is the container
    open", and a tool that trusts it will write plaintext case material to
    the bare mountpoint, outside the encryption, without saying a word.
    ismount() is the only test that answers the question being asked.
    """
    return os.path.ismount(PROJECTS)

def _resolve_root():
    """TR_ROOT wins. Otherwise use the active project recorded in .active."""
    explicit = os.environ.get("TR_ROOT")
    if explicit:
        return explicit
    marker = os.path.join(PROJECTS, ".active")
    if os.path.exists(marker):
        name = open(marker, encoding="utf-8").read().strip()
        if name:
            return os.path.join(PROJECTS, name)
    return None

ROOT = _resolve_root()

def _load_project_conf():
    """Per-project defaults: language pair, suffix, OCR languages.

    tr-run sourced project.conf before dispatching, so batch runs saw these
    settings and anything invoked directly did not. That is how tr-status
    came to report an entire corpus as missing whenever a project set
    TR_SUFFIX -- tr-run renamed the outputs and tr-status did not know it.
    Loading the file here means every entry point agrees.

    Parsed rather than sourced: project.conf is data, and sourcing it would
    execute whatever it contains. An explicit environment setting is a
    deliberate one-off override and wins over the file.
    """
    if not ROOT:
        return
    conf = os.path.join(ROOT, "project.conf")
    if not os.path.exists(conf):
        return
    for ln in open(conf, encoding="utf-8"):
        ln = ln.split("#")[0].strip()
        if "=" not in ln:
            continue
        k, _, v = ln.partition("=")
        k, v = k.strip(), v.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            continue
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        os.environ.setdefault(k, v)

_load_project_conf()

# Output extension by source extension. A scanned PDF cannot be regenerated
# as a PDF and plain text has no formatting to preserve, so both deliver a
# .docx. bin/tr-run mirrors this table in out_ext_for() -- the two must
# agree, or tr-run writes one name and tr-status looks for another and every
# affected file reports as missing forever.
OUT_EXT = {".pdf": ".docx", ".txt": ".docx"}

def manifest_paths(lang=None):
    """Source-relative paths from the tr-inventory manifest.

    Returns None when no manifest exists -- which means triage has not been
    run, not that there are no files. Callers must tell those apart: with a
    mixed-language drop, translating everything is the expensive mistake.
    """
    mf = os.path.join(ROOT or "", "work", "inventory", "manifest.tsv")
    if not ROOT or not os.path.exists(mf):
        return None
    out = []
    with open(mf, encoding="utf-8") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        try:
            i_path, i_lang = head.index("path"), head.index("lang")
        except ValueError:
            return None
        for ln in fh:
            cols = ln.rstrip("\n").split("\t")
            if len(cols) > max(i_path, i_lang):
                if lang is None or cols[i_lang] == lang:
                    out.append(cols[i_path])
    return out


def target_name(rel, suffix=None):
    """The deliverable's name for a source file: suffix applied, extension
    mapped. Filenames are otherwise preserved -- design invariant 1."""
    if suffix is None:
        suffix = os.environ.get("TR_SUFFIX", "")
    stem, ext = os.path.splitext(rel)
    if not ext:
        return rel + suffix
    return stem + suffix + OUT_EXT.get(ext.lower(), ext)

def require_root():
    """Fail loudly rather than writing into the wrong project.

    Refuses outright when the target sits under a container that is not
    mounted: that is not "no project yet", it is "you are about to write
    case material to an unencrypted directory".
    """
    if (ROOT and _under(ROOT, PROJECTS)
            and not PROJECTS_OVERRIDDEN and not container_mounted()):
        sys.stderr.write(
            "\nThe case container is NOT mounted.\n"
            f"  mountpoint: {PROJECTS}\n"
            "  Anything written there now would be plaintext, outside the\n"
            "  encryption. Refusing.\n"
            "  open it:    case-open        (check first: case-status)\n"
            "  never set up? case-init 40G\n\n")
        sys.exit(2)
    if not ROOT or not os.path.isdir(ROOT):
        sys.stderr.write(
            "\nNo active project.\n"
            f"  container root: {PROJECTS}\n"
            "  choose one:     tr-project <name>\n"
            "  list:           tr-project\n"
            "  or set TR_ROOT explicitly for a one-off.\n\n")
        sys.exit(2)
    return ROOT

def project_name():
    return os.path.basename(ROOT.rstrip("/")) if ROOT else "(none)"

MODEL = os.environ.get("TR_MODEL", "gams3:q8")
OLLAMA = os.environ.get("TR_OLLAMA", "http://127.0.0.1:11434")
NUM_CTX = int(os.environ.get("TR_NUM_CTX", "8192"))
PROMPT_VERSION = os.environ.get("TR_PROMPT_VERSION", "v1")

def path(*p):
    return os.path.join(require_root(), *p)

def shared(*p):
    return os.path.join(SHARED, *p)

# ---------------------------------------------------------------- segmentation

# Abbreviations whose trailing period must NOT end a sentence.
# Slovene legal/administrative text is dense with these; leaving them out
# shatters segments and makes sentence-by-sentence review painful.
ABBREV = [
    # Slovene legal / administrative
    "št", "čl", "odst", "tč", "al", "odd", "pt", "str", "op", "cit",
    "ur", "l", "npr", "oz", "ipd", "itd", "tj", "prim", "gl", "sl",
    "g", "ga", "dr", "mag", "univ", "prof", "inž", "ing",
    "d.o.o", "d.d", "d.n.o", "k.d", "s.p", "z.o.o",
    "r.š", "e.š", "davč", "mat", "reg",
    # English legal
    "no", "art", "sec", "para", "pp", "cf", "eg", "ie", "etc", "vs", "v",
    "mr", "mrs", "ms", "jr", "sr", "inc", "ltd", "co", "corp",
    # German
    "bzw", "ggf", "usw", "z.B", "u.a", "Abs", "Nr", "vgl", "Bd",
]
_ABBR_RE = re.compile(
    r"(?:\b(?:" + "|".join(re.escape(a) for a in ABBREV) + r")\.)$",
    re.IGNORECASE)
_ROMAN_RE = re.compile(r"\b[IVXLCDM]+\.$")
_INITIAL_RE = re.compile(r"\b[A-ZČŠŽÄÖÜ]\.$")
# 1-3 digits: list numbering or a day/month in a date -> not a boundary.
# 4 digits: almost always a year ending the sentence -> is a boundary.
_NUMBERED_RE = re.compile(r"(?:^|\s)\d{1,3}(?:\.\d{1,3})*\.$")

_BOUNDARY = re.compile(r"(?<=[.!?:;])[\s\u00a0]+")

def segment(text):
    """Split text into review-sized segments, respecting abbreviations."""
    text = re.sub(r"[\r\u00a0]", " ", text or "").strip()
    if not text:
        return []
    if "\n" in text:                       # newlines are hard boundaries
        out = []
        for line in text.split("\n"):
            out.extend(segment(line))
        return out
    parts, buf = [], ""
    for chunk in _BOUNDARY.split(text):
        buf = (buf + " " + chunk).strip() if buf else chunk
        tail = buf.rstrip()
        if (_ABBR_RE.search(tail) or _ROMAN_RE.search(tail)
                or _INITIAL_RE.search(tail) or _NUMBERED_RE.search(tail)):
            continue                      # false boundary: keep accumulating
        if tail.endswith((".", "!", "?", ":", ";")) or len(tail) > 400:
            parts.append(tail)
            buf = ""
    if buf.strip():
        parts.append(buf.strip())
    return [p for p in parts if p.strip()]

# ---------------------------------------------------------------- translatable

_NONTRANS_CACHE = None

def nontranslatables():
    """Shared patterns plus any project-specific additions.

    The project overlay is resolved only when a project is actually active.
    Both arguments of a tuple are evaluated before the loop body runs, so
    naming path() unconditionally called require_root() and exited even for
    callers that need no project at all -- tr-xlsx --survey, for one, which
    only classifies cells and never touches the memory or the model.

    Outside a project the pattern list is the shared set alone, so counts
    can differ from the same command run inside one. That is said out loud
    rather than left to be discovered.
    """
    global _NONTRANS_CACHE
    if _NONTRANS_CACHE is None:
        files = [shared("glossary", "nontranslatable.txt")]
        if ROOT and os.path.isdir(ROOT):
            files.append(path("glossary", "nontranslatable.txt"))
        else:
            sys.stderr.write(
                "note: no active project -- non-translatable patterns are the "
                "shared set only.\n      Counts may differ from a run inside a "
                "project.\n")
        pats = []
        for f in files:
            if not os.path.exists(f):
                continue
            for ln in open(f, encoding="utf-8"):
                ln = ln.split("#")[0].strip()
                if ln:
                    pats.append(re.compile(ln))
        _NONTRANS_CACHE = pats
    return _NONTRANS_CACHE

def is_translatable(s):
    """False for strings that must be reproduced verbatim."""
    s = (s or "").strip()
    if len(s) < 2:
        return False
    if not re.search(r"[A-Za-zČčŠšŽžÄäÖöÜüß]{2,}", s):
        return False          # pure numbers, dates, codes, punctuation
    for p in nontranslatables():
        if p.fullmatch(s):
            return False
    return True

# ---------------------------------------------------------------- glossary

def load_glossary():
    """Shared base terminology, then project terms. Project wins on conflict.

    Base holds general legal terminology reusable across matters. The project
    file holds case-specific renderings. Keeping them separate means a new
    project inherits settled terminology without inheriting case content.
    """
    merged = {}
    # The project overlay is resolved only when a project is actually
    # active, for the reason spelled out in nontranslatables(): naming
    # path() evaluates require_root() even for a caller that needs no
    # project, and exits.
    files = [shared("glossary", "base.tsv")]
    if ROOT and os.path.isdir(ROOT):
        files += [path("glossary", "project.tsv"),
                  path("glossary", "glossary.tsv")]   # legacy flat name
    for f in files:
        if not os.path.exists(f):
            continue
        for ln in open(f, encoding="utf-8"):
            if ln.startswith("#") or not ln.strip():
                continue
            cols = ln.rstrip("\n").split("\t")
            if len(cols) >= 2 and cols[0].strip() and cols[1].strip():
                merged[cols[0].strip()] = cols[1].strip()
    return sorted(merged.items())

def glossary_block(text, gloss, limit=40):
    """Only inject terms that actually occur — keeps the prompt small.
    NOTE: the block is sorted so identical term sets produce identical
    prompts, which lets the inference engine reuse its cached prefix."""
    low = text.lower()
    hits = sorted({(s, t) for s, t in gloss if s.lower() in low})[:limit]
    if not hits:
        return ""
    return "Required terminology:\n" + "\n".join(f"  {s} -> {t}" for s, t in hits)

# ---------------------------------------------------------------- cache / TM

def _db():
    os.makedirs(path("work"), exist_ok=True)
    db = sqlite3.connect(path("work", "tm.sqlite"), timeout=60)
    db.execute("""CREATE TABLE IF NOT EXISTS tm(
        key TEXT PRIMARY KEY, src TEXT, tgt TEXT, direction TEXT,
        model TEXT, prompt_version TEXT, ts REAL)""")
    return db

def _key(src, direction):
    h = hashlib.sha256()
    h.update(f"{direction}\x00{MODEL}\x00{PROMPT_VERSION}\x00{src}".encode())
    return h.hexdigest()

def tm_get(src, direction):
    db = _db()
    r = db.execute("SELECT tgt FROM tm WHERE key=?", (_key(src, direction),)).fetchone()
    db.close()
    return r[0] if r else None

def tm_put(src, tgt, direction):
    db = _db()
    db.execute("INSERT OR REPLACE INTO tm VALUES(?,?,?,?,?,?,?)",
               (_key(src, direction), src, tgt, direction, MODEL,
                PROMPT_VERSION, time.time()))
    db.commit(); db.close()

# ---------------------------------------------------------------- model

LANG = {"sl": "Slovene", "en": "English", "de": "German"}

def build_prompt(src_lang, tgt_lang, gloss_block):
    base = _DEFAULT_PROMPT
    tpls = [shared("prompts", "translate.txt")]
    if ROOT and os.path.isdir(ROOT):                 # see load_glossary()
        tpls.append(path("prompts", "translate.txt"))   # project overrides shared
    for tpl in tpls:
        if os.path.exists(tpl):
            base = open(tpl, encoding="utf-8").read()
    return base.replace("{SRC}", LANG.get(src_lang, src_lang)) \
               .replace("{TGT}", LANG.get(tgt_lang, tgt_lang)) \
               .replace("{GLOSSARY}", gloss_block)

_DEFAULT_PROMPT = """You are translating {SRC} legal documents into {TGT} for court proceedings.

Rules:
- Output ONLY the translation. No preamble, notes, or explanation.
- Preserve meaning exactly. Do not summarize, expand, or improve the source.
- Reproduce verbatim, untranslated: case numbers, file numbers, statutory
  citations, article and paragraph references, institution names, personal
  names, addresses, dates, and monetary amounts.
- Preserve all numbers exactly as written.
- If a passage is illegible or garbled, output [ILLEGIBLE] in its place
  rather than guessing what it might have said.
- Match the formal register of legal documents.

{GLOSSARY}"""

def ollama_translate(text, src_lang, tgt_lang, gloss=None, retries=3):
    if not is_translatable(text):
        return text
    cached = tm_get(text, f"{src_lang}-{tgt_lang}")
    if cached is not None:
        return cached
    gb = glossary_block(text, gloss or [])
    payload = {
        "model": MODEL,
        "system": build_prompt(src_lang, tgt_lang, gb),
        "prompt": text,
        "stream": False,
        "options": {"temperature": 0.1, "top_p": 0.9, "num_ctx": NUM_CTX},
    }
    req = urllib.request.Request(
        OLLAMA + "/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=1800) as r:
                out = json.loads(r.read())["response"].strip()
            out = re.sub(r"^```.*?\n|```$", "", out, flags=re.S).strip()
            if out:
                tm_put(text, out, f"{src_lang}-{tgt_lang}")
                return out
            last = "empty response"
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))
    print(f"  ! translation failed after {retries} tries: {last}", file=sys.stderr)
    return f"[TRANSLATION FAILED] {text}"

def progress(i, n, label=""):
    pct = 100.0 * i / n if n else 100.0
    sys.stderr.write(f"\r  {i}/{n} ({pct:.0f}%) {label[:50]:<50}")
    sys.stderr.flush()
    if i == n:
        sys.stderr.write("\n")
