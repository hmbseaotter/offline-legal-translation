"""Shared helpers for the offline translation pipeline.

Nothing here talks to the network except ollama_translate(), which speaks
only to http://127.0.0.1:11434 (the local Ollama daemon).
"""
import os, re, json, sqlite3, hashlib, urllib.request, sys, time, tempfile
import calendar, collections

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

# The kit root, two levels up from lib/trlib.py. The prompt and the
# glossary base live here and travel with the repository.
KIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
        # One spelling, as lib/guard.sh gives the shell tools: a trailing
        # slash, which tab completion adds, gave tr-pdf a different cache key
        # from the one tr-inventory looked for.
        return os.path.normpath(os.path.abspath(explicit))
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
# .docx. bin/tr-run calls target_name() rather than keeping its own copy of
# this table. It used to keep one, and when they drifted tr-run wrote one
# name while tr-status looked for another, so every affected file reported as
# missing forever.
#
# Macro-enabled and template workbooks deliver as a plain .xlsx. openpyxl
# reads them all, but writing one back drops the macro project unless it is
# carried through deliberately -- and a file that still calls itself .xlsm
# while no longer containing macros is worse than one that does not claim to.
# The deliverable is a translation, not a working copy of the client's
# tooling, and unexamined macros out of a client drop are not something to
# pass on to a court.
OUT_EXT = {".pdf": ".docx", ".txt": ".docx",
           ".xlsm": ".xlsx", ".xltx": ".xlsx", ".xltm": ".xlsx"}

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


# Characters XML forbids outright. python-docx hands text to lxml, which
# rejects these with "All strings must be XML compatible" and takes the whole
# file down at the last step, after every segment has been translated.
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0e-\x1f\ufffe\uffff]")


def xml_safe(text):
    """Text that a .docx can actually hold.

    pdftotext separates pages with a form feed. Nothing in the OCR path ever
    produced one -- tr-ocrtext rebuilds its text from Tesseract's TSV -- so
    the writers never met a control character until born-digital PDFs began
    using pdftotext output directly. Then a 47-segment file translated for
    several minutes and died writing the document, losing all of it.

    A form feed is a page break, so it becomes a paragraph break rather than
    disappearing. The rest carry no meaning in a legal document and are
    dropped.

    Applied at every point text enters a document, not only where the bug
    appeared: the cost is a regex over a string, and the failure it prevents
    is the loss of a whole file's work at the very end.
    """
    if not text:
        return text
    return _XML_ILLEGAL.sub("", text.replace("\f", "\n"))


def target_name(rel, suffix=None):
    """The deliverable's name for a source file on its own: suffix applied,
    extension mapped. Filenames are otherwise preserved -- design invariant 1.
    Where files in one folder would share a name, target_names() decides."""
    if suffix is None:
        suffix = os.environ.get("TR_SUFFIX", "")
    stem, ext = os.path.splitext(rel)
    if not ext:
        return rel + suffix
    return stem + suffix + OUT_EXT.get(ext.lower(), ext)


def target_names(rels, suffix=None):
    """({rel: deliverable name}, clashes) for source files given relative to
    source/. Pass every file in source/, not only the ones being worked on:
    whether a name is shared depends on the whole folder.

    Each file keeps target_name()'s name unless two or more files in one
    folder would deliver under it -- x.docx beside x.pdf, t.xlsx beside
    t.xlsm. Then a file whose format changes keeps its extension and takes
    the new one after it: x.pdf delivers as x.pdf.docx, x.txt as x.txt.docx,
    t.xlsm as t.xlsm.xlsx, while x.docx and t.xlsx keep their names. With
    TR_SUFFIX set, x.pdf delivers as x<suffix>.pdf.docx. A drop holding one
    document as Word and as a signed PDF is ordinary, and one name for both
    had the file translated last overwrite the other without a word.

    Names are compared without regard to case, because a deliverable folder
    copied to Windows or macOS would overwrite one with the other there.
    clashes lists the groups of files still sharing a name after this -- two
    names differing only in case, or a source already called x.pdf.docx --
    which tr-run refuses to translate.
    """
    if suffix is None:
        suffix = os.environ.get("TR_SUFFIX", "")
    names = {rel: target_name(rel, suffix) for rel in rels}

    def groups():
        out = collections.defaultdict(list)
        for rel, name in names.items():
            out[name.casefold()].append(rel)
        return [sorted(g) for g in out.values() if len(g) > 1]

    for group in groups():
        for rel in group:
            stem, ext = os.path.splitext(rel)
            if ext.lower() in OUT_EXT:
                names[rel] = stem + suffix + ext + OUT_EXT[ext.lower()]
    return names, sorted(groups())


def source_files():
    """Every file under source/, relative to it, as tr-run and tr-status see
    the drop: office lock files (~$...) and hidden files left out."""
    root = path("source")
    out = []
    for dp, _dirs, files in os.walk(root):
        out.extend(os.path.relpath(os.path.join(dp, f), root) for f in files
                   if not f.startswith(("~$", ".")))
    return sorted(out)


def ocr_layer(rel):
    """The text layer tr-pdf makes for source/<rel>: the path without its
    extension, / written __, under work/ocr/. tr-pdf names it the same way."""
    return path("work", "ocr", os.path.splitext(rel)[0].replace(os.sep, "__") + ".txt")


# What work/deliverables.tsv records about each deliverable -- everything
# that shapes it:
#
#   path, output            the source file, and its deliverable's name
#   model, prompt_version   what drafted its segments
#   source, layer           hashes of the source file and, for a PDF, of the
#                           text layer it was translated from
#   glossary                the glossary and the non-translatable patterns
#   references              what tr-ref kept for the language pair
#   drafting                the kit code that turns segments into a file
#   written, delivered      when tr-run wrote it, and a hash of what it wrote
#
# deliverable_plan() drafts a file again when any of these has changed. The
# test was "output newer than source, by the same model and prompt", and a
# pinned glossary term, a reference kept later, an OCR layer read again and a
# fix to how drafts are finished each left a delivered file current by it,
# so none of them reached work already delivered.
DELIVERABLE_COLUMNS = ("path", "model", "prompt_version", "written", "output",
                       "source", "layer", "glossary", "references", "drafting",
                       "delivered")
# The kit files that turn memory rows and references into a deliverable. The
# prompt is not one of them: prompt_version says when this pair's prompt
# changed, and another pair's rules do not reach it.
DRAFTING_FILES = ("lib/trlib.py", "lib/trref.py", "bin/tr-docx", "bin/tr-txt",
                  "bin/tr-xlsx", "bin/tr-pdf", "bin/tr-ocrtext",
                  "glossary/nontranslatable.txt")


def _file_digest(p):
    """A short hash of a file's contents, or "" when there is no file."""
    if not os.path.exists(p):
        return ""
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def glossary_signature():
    """The glossary and the non-translatable patterns in force, as one hash."""
    state = (load_glossary(), [p.pattern for p in nontranslatables()])
    return hashlib.sha256(repr(state).encode()).hexdigest()[:16]


def drafting_version():
    """The kit code that shapes a deliverable, as one hash."""
    h = hashlib.sha256()
    for rel in DRAFTING_FILES:
        h.update(f"{rel}\x00{_file_digest(os.path.join(KIT_DIR, rel))}\x00".encode())
    return h.hexdigest()[:16]


def _deliverable_rows():
    """work/deliverables.tsv as dicts, in the order tr-run wrote them. A
    column a row predates is empty."""
    tsv = path("work", "deliverables.tsv")
    if not os.path.exists(tsv):
        return []
    with open(tsv, encoding="utf-8") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        return [dict(zip(head, cols + [""] * (len(head) - len(cols))))
                for cols in (ln.rstrip("\n").split("\t") for ln in fh) if cols[0]]


def deliverable_writers():
    """{deliverable name, casefolded: the source file that last wrote it}. A
    row from before the output column is read as written under target_name(),
    which is where every file was written then."""
    return {(row.get("output") or target_name(row["path"])).casefold(): row["path"]
            for row in _deliverable_rows()}


class _Now:
    """What would make a deliverable now, in DELIVERABLE_COLUMNS' terms. The
    parts every file shares are worked out once."""

    def __init__(self):
        import trref
        self.shared = {
            "model": MODEL or "(none)", "prompt_version": PROMPT_VERSION,
            "glossary": glossary_signature(), "drafting": drafting_version(),
            "references": trref.digest(
                f"{os.environ.get('TR_SRC', 'sl')}-{_env_target()}")}

    def of(self, rel):
        return dict(self.shared, source=_file_digest(path("source", rel)),
                    layer=(_file_digest(ocr_layer(rel))
                           if rel.lower().endswith(".pdf") else "-"))


_CHANGED = {"model": "the model", "prompt_version": "the prompt",
            "source": "the source file", "layer": "the text layer",
            "glossary": "the glossary", "references": "the reference translations",
            "drafting": "the kit's drafting code"}


def _changes(row, now):
    """What has changed since row's deliverable was written, in words."""
    if not row.get("source"):
        return ["written before tr-run recorded what makes a deliverable"]
    out = []
    for key, what in _CHANGED.items():
        if row.get(key, "") != now[key]:
            was = (f" ({row.get(key) or 'none'} -> {now[key]})"
                   if key in ("model", "prompt_version") else "")
            out.append(f"{what} changed{was}")
    return out


def _edited(out, row):
    """Has this deliverable changed since tr-run wrote it? By its hash where
    the row records one; for a row from before, by whether it was saved more
    than two minutes after the row was written."""
    if not row:
        return False
    if row.get("delivered"):
        return _file_digest(out) != row["delivered"]
    try:
        written = calendar.timegm(time.strptime(row.get("written", ""),
                                                "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return False
    return os.path.getmtime(out) > written + 120


def deliverable_plan(rels, outdir=None):
    """{rel: (deliverable name, action, detail)} for source files relative to
    source/: what tr-run does with each, and what tr-status reports.

      draft    no deliverable yet
      current  nothing that made the deliverable has changed
      redo     detail says what has
      held     the deliverable holds the translation of another source file,
               named in detail
      edited   a redo, or a held file, whose deliverable has changed since
               tr-run wrote it -- a translator's corrections, most likely. It
               is never overwritten; moved aside, it is drafted again
      clash    another source file delivers under the same name (detail)
    """
    outdir = outdir or path("translated")
    names, clashes = target_names(sorted(set(source_files()) | set(rels)))
    clash = {r: group for group in clashes for r in group}
    rows = {row["path"]: row for row in _deliverable_rows()}
    writers = deliverable_writers()
    now = _Now()
    plan = {}
    for rel in rels:
        name = names[rel]
        out = os.path.join(outdir, name)
        by = writers.get(name.casefold())
        if rel in clash:
            action, detail = "clash", ", ".join(r for r in clash[rel] if r != rel)
        elif not os.path.exists(out):
            action, detail = "draft", ""
        elif by not in (None, rel):
            action, detail = "held", by
            if _edited(out, rows.get(by)):
                action, detail = "edited", f"it holds the translation of {by}"
        else:
            row = rows.get(rel)
            reasons = (_changes(row, now.of(rel)) if row
                       else ["nothing records what made it"])
            action, detail = ("current", "") if not reasons else \
                ("edited" if _edited(out, row) else "redo", "; ".join(reasons))
        plan[rel] = (name, action, detail)
    return plan


def record_deliverable(rel, name, outdir=None):
    """Write rel's row in work/deliverables.tsv for the deliverable tr-run has
    just written: what made it, and a hash of it. The row moves to the end,
    so the file stays in the order deliverables were written."""
    outdir = outdir or path("translated")
    row = dict(_Now().of(rel), path=rel, output=name,
               written=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               delivered=_file_digest(os.path.join(outdir, name)))
    _write_deliverables([r for r in _deliverable_rows() if r["path"] != rel] + [row])


def forget_deliverable(rel):
    """Drop rel's row from work/deliverables.tsv. tr-run calls this when a
    worker fails: whatever is on disk -- half written, or holding
    [TRANSLATION FAILED] -- is not current, and without a row the next run
    drafts it again rather than taking it for a translator's edit."""
    rows = _deliverable_rows()
    if any(r["path"] == rel for r in rows):
        _write_deliverables([r for r in rows if r["path"] != rel])


def _write_deliverables(rows):
    tsv = path("work", "deliverables.tsv")
    os.makedirs(os.path.dirname(tsv), exist_ok=True)
    # Written beside itself and renamed, inside the container: a temporary
    # file elsewhere would put paths -- which carry party names -- on the
    # unencrypted root.
    with open(tsv + ".tmp", "w", encoding="utf-8") as fh:
        fh.write("\t".join(DELIVERABLE_COLUMNS) + "\n")
        for r in rows:
            fh.write("\t".join(r.get(k, "") for k in DELIVERABLE_COLUMNS) + "\n")
    os.replace(tsv + ".tmp", tsv)

def require_root():
    """Fail loudly rather than writing into the wrong project.

    Refuses outright when the target sits under a container that is not
    mounted: that is not "no project yet", it is "you are about to write
    case material to an unencrypted directory".

    The mount is checked before the project, and that order matters. The
    .active marker lives INSIDE the container, so while it is closed the
    marker cannot be read, ROOT is None, and a mount test written as
    `ROOT and ...` never fires. Every Python tool then reported "no active
    project" and advised running tr-project -- which cannot work, because
    the thing that records the active project is inside the container the
    user has not opened. tr-run, being bash and checking the mountpoint
    first, gave the right diagnosis all along; the two now agree.
    """
    if ((ROOT is None or _under(ROOT, PROJECTS))
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

OLLAMA = os.environ.get("TR_OLLAMA", "http://127.0.0.1:11434")
NUM_CTX = int(os.environ.get("TR_NUM_CTX", "8192"))

# ------------------------------------------------------- language variants

# German is written differently in Germany, Austria and Switzerland, and a
# deliverable shows it: Switzerland writes ss where Germany writes ß, and
# spells amounts and times its own way. A project names its variant in
# TR_TGT: de-DE, de-AT or de-CH.
#
# Plain de is Germany, and so is de-DE; lang_code() turns both into "de". The
# memory keys on the direction, and an English->German project already has a
# memory written under en-de. Were de-DE a spelling of its own, setting it
# would file the same work under a new direction and find none of what is
# already there.
#
# Only the target takes a variant. A German source is refused altogether for
# now (project_pair): language detection has no German class, so tr-inventory
# files German documents under another language.
SOURCES = ("sl", "en")
VARIANTS = {"de": ("DE", "AT", "CH")}      # the first is what the bare code means

# The variants a draft can be made in, beyond each language's first. Swiss
# German has prompt rules, conversions and a spelling pass of its own, from
# the Swiss Federal Chancellery's Schreibweisungen: see localize() and
# finish_draft(). Austrian German has none settled, and a draft made by
# Germany's rules would read as finished, so it is refused. References in
# every variant are filed by tr-ref and read by tr-terms regardless.
VARIANTS_DRAFTED = {"de-CH"}

_LANG_RE = re.compile(r"([A-Za-z]{2})(?:[-_]([A-Za-z]{2}))?")


def lang_code(code):
    """One spelling for a language setting: 'de' and 'de-DE' give 'de',
    'de_ch' gives 'de-CH', 'en' gives 'en'. None when the setting names a
    variant its language does not have, or is not a language code at all."""
    m = _LANG_RE.fullmatch((code or "").strip())
    if not m:
        return None
    lang, region = m.group(1).lower(), (m.group(2) or "").upper()
    if not region:
        return lang
    known = VARIANTS.get(lang, ())
    if region not in known:
        return None
    return lang if region == known[0] else f"{lang}-{region}"


def base_lang(code):
    """The language without its variant: 'de' for 'de-CH'."""
    return (code or "").replace("_", "-").split("-", 1)[0].lower()


def split_direction(direction):
    """(source, target) for a direction: ('en', 'de-CH') for 'en-de-CH'.

    Split at the first hyphen only, because only the target has a variant.
    Taking the first two parts, as _key(), tm_put() and tr-lint each did,
    would read en-de-CH as en-de: a Swiss segment keyed under Germany's
    prompt version, where a Germany run would find and reuse it.
    """
    s, _, t = (direction or "").partition("-")
    return s, t


def project_pair(src=None, tgt=None):
    """(source, target) in lang_code()'s spelling, from TR_SRC and TR_TGT
    unless given. Exits naming the setting when either cannot be read."""
    src = os.environ.get("TR_SRC", "sl") if src is None else src
    tgt = os.environ.get("TR_TGT", "en") if tgt is None else tgt
    if not re.fullmatch(r"[a-z]{2}", src):
        sys.exit(f"TR_SRC is {src!r}. Name the source language alone - "
                 f"{', '.join(SOURCES)}. Only TR_TGT takes a variant, such as de-CH.")
    if src == "de":
        sys.exit("TR_SRC is de, and a German source is not supported yet. Language "
                 "detection has no German, so tr-inventory would file German "
                 "documents under English or Croatian and tr-run would find nothing "
                 "to translate; and German->English has no prompt rules or "
                 f"conversions of its own. Sources: {', '.join(SOURCES)}.")
    if src not in SOURCES:
        sys.exit(f"TR_SRC is {src}, which is no source language this kit knows. "
                 f"Sources: {', '.join(SOURCES)}.")
    t = lang_code(tgt)
    if t is None or base_lang(t) not in LANG:
        variants = ", ".join(f"{lang}-{r}" for lang, rs in VARIANTS.items()
                             for r in rs)
        sys.exit(f"TR_TGT is {tgt!r}, which is no language or variant this kit "
                 f"knows. The languages are {', '.join(LANG)}; the variants "
                 f"are {variants}.")
    if base_lang(t) == src:
        sys.exit(f"TR_SRC and TR_TGT are both {src} - set the pair in "
                 f"project.conf first")
    return src, t


def translation_pair(src=None, tgt=None):
    """project_pair(), refusing a target no draft can be made in yet, and a
    prompt override that would draft without the per-language rules."""
    global _OVERRIDE_NOTED
    s, t = project_pair(src, tgt)
    # A pair no model is chosen for is refused here, before a worker counts
    # its segments or tr-run -n lists what it would draft.
    require_model(s, t)
    if t != base_lang(t) and t not in VARIANTS_DRAFTED:
        sys.exit(f"TR_TGT is {t}, and drafting into it is not built yet: no "
                 f"prompt rules or conversions of dates, amounts and times "
                 f"exist for it, and a draft made by Germany's rules would read "
                 f"as finished.\n"
                 f"tr-ref and tr-terms --reference already work for {t}. "
                 f"For Germany, set TR_TGT=de; for Switzerland, TR_TGT=de-CH.")
    # A copy of the prompt made before the rules were split by language has no
    # {when} blocks, and replaces the kit's file wholesale: German and Swiss
    # drafts would get Slovene date rules and none of their own, under one
    # prompt version, with nothing said. Refused; any override is named.
    override = prompt_override()
    if override:
        with open(override, encoding="utf-8") as fh:
            blocks = "{when" in fh.read()
        if not blocks:
            sys.exit(f"{override} replaces the kit's prompt, and has no {{when}} "
                     f"blocks: every rule that differs by language -- dates, amounts, "
                     f"times, German and Swiss conventions -- would be missing from "
                     f"{s} -> {t}.\nDelete it to draft with the kit's "
                     f"prompts/translate.txt, or rebuild it from that file.")
        if not _OVERRIDE_NOTED:
            _OVERRIDE_NOTED = True
            sys.stderr.write(f"  note: the prompt is {override}, not the kit's "
                             f"(version {prompt_version(s, t)})\n")
    return s, t


_OVERRIDE_NOTED = False


def _env_target():
    """TR_TGT in lang_code()'s spelling, or as written when it cannot be read:
    for the values worked out on import, which report and must not exit."""
    t = os.environ.get("TR_TGT", "en")
    return lang_code(t) or t


# Which model translates which pair.
#
# GaMS3 is continually pretrained on Slovene, English, Bosnian, Serbian and
# Croatian. German is absent from every stage, so the German it has is
# residue of the base Gemma. It was the model for everything only because
# sl<->en was the only pair. EuroLLM covers every EU official language and
# has translation in its instruction tuning.
#
# Routed here rather than left to TR_MODEL, because forgetting fails
# silently: a German project that did not set the variable would be drafted
# by the Slovene model and look finished. TR_MODEL still wins, set in a
# project's project.conf -- not in ~/.bashrc, where it would send every pair
# of every project to one model.
#
# Slovene<->German has no entry. The model researched for it (EuroLLM-22B)
# is not installed, and pivoting through English doubles the error, so
# translating refuses until a model is chosen.
PAIR_MODELS = {
    ("sl", "en"): "gams3:q8",
    ("en", "sl"): "gams3:q8",
    ("en", "de"): "eurollm9b-2512:q8",
    ("de", "en"): "eurollm9b-2512:q8",
}


def model_for(src_lang, tgt_lang):
    """TR_MODEL when set; otherwise the model routed for the pair, or "".
    Routed by language, so a variant goes to its language's model."""
    return os.environ.get("TR_MODEL") or PAIR_MODELS.get(
        (base_lang(src_lang), base_lang(tgt_lang)), "")


def require_model(src_lang, tgt_lang):
    m = model_for(src_lang, tgt_lang)
    if not m:
        sys.exit(f"no model is chosen for {src_lang} -> {tgt_lang}.\n"
                 f"Set TR_MODEL in this project's project.conf. Do not use "
                 f"gams3:q8 for German: German is not in its training.")
    return m


# The model for this project's pair, for the tools that report on one.
MODEL = model_for(os.environ.get("TR_SRC", "sl"), _env_target())

# Seconds per segment, end to end, by model. Measured on this machine, never
# estimated from a tokens-per-second figure: that was optimistic by ~5x,
# because most of a segment's cost was not generation.
#
#   gams3:q8           48.3  12 samples of real sl->en pipeline traffic.
#                            Prefill 7.00 tok/s, generation 2.20 tok/s: every
#                            call re-reads the system prompt, about 28 s, and
#                            pays it whether the cell holds a sentence or two
#                            words.
#   eurollm9b-2512:q8  10.5  Median of 42 requests, 14 invented en->de
#                            segments three times, with the German prompt,
#                            Ollama 0.30.9. Prefill ~220 tok/s, generation
#                            3.0 tok/s, no request failed. Here generation
#                            is most of the cost, so batching saves less
#                            than it did for GaMS3.
#
# One table, read by tr-inventory and tr-xlsx. It used to be a constant in
# each with a note that both must move together.
SEC_PER_SEGMENT = {
    "gams3:q8": 48.3,
    "eurollm9b-2512:q8": 10.5,
}


def sec_per_segment(model=None):
    """(seconds, measured) for a model. Unmeasured falls back to the slowest
    figure there is, and says so -- an estimate that errs long is a delay,
    one that errs short is a mispriced job."""
    m = MODEL if model is None else model
    if m in SEC_PER_SEGMENT:
        return SEC_PER_SEGMENT[m], True
    return max(SEC_PER_SEGMENT.values()), False

def path(*p):
    return os.path.join(require_root(), *p)

def shared(*p):
    return os.path.join(SHARED, *p)


def case_tmpdir(prefix):
    """A scratch directory that stays inside the encrypted container.

    WHY NOT tempfile.mkdtemp()

    Rendering a scanned page writes a picture of that page out. The plain
    mkdtemp puts it under TMPDIR, and every source document in this corpus
    is a scan -- so a full run pushes the entire evidence bundle through
    that directory as PNGs.

    On this machine /tmp is tmpfs, so those images are not written to the
    SSD and do not survive a reboot. That is better than it first looks
    and still not good enough: tmpfs lives in RAM, RAM is swapped under
    pressure, and the swapfile is 8 GB of plain ext4 on the root
    filesystem. Memory pressure is not hypothetical here -- the
    translation model alone is 13 GB and the vision model 23 GB on a 30 GB
    machine, which is why the setup adds swap in the first place. So the
    realistic path for a page image onto the persistent disk is through
    swap, and an unlinked page there is not reliably gone: wear levelling
    is exactly why the container document says not to trust shred.

    Nor is cleanup guaranteed. Callers remove these directories in a
    finally, which a hard kill skips -- two renders from an interrupted run
    were found still sitting in /tmp days later.

    The decisions register does accept "swap, temporary files ... are in
    the clear" as residual risk. That wording was written imagining an
    editor's swap file, not a systematic render of every page of every
    exhibit, and the difference is large enough to close rather than reason
    past. Inside the container the same images are encrypted at rest and
    go away with the unmount.

    There is deliberately no fallback. require_root() already refuses with
    a readable message when no project is selected, and every caller here
    needs a project anyway. A silent fall back to /tmp -- on a missing
    project, a full disk, a permissions error -- would restore exactly the
    exposure this exists to close, at the moment least likely to be
    noticed. Failing loudly is the point.
    """
    base = path("work", "tmp")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=base)


def ocr_layer_unmarked(txt):
    """Was this cached text layer written without confidence marking?

    tr-inventory --count --with-ocr used to write work/ocr/<name>.txt itself,
    with pdftotext over ocrmypdf's output. It predated tr-ocrtext by an hour
    and a half and was never moved onto it. tr-pdf finds a cached text layer
    and uses it rather than OCR the file again -- which is the point of the
    cache -- so on the documented path the step that marks unreadable words
    OCR_ILLEGIBLE never ran, and tr-ocrstat, counting marks that were never
    written, reported every file as legible.

    The tell is the form feed. pdftotext writes one after every page, even a
    one-page document, unless given -nopgbrk. tr-ocrtext joins pages with a
    blank line and never writes one, and tr-pdf's born-digital branch passes
    -nopgbrk. So a form feed means the layer came from somewhere that did not
    keep Tesseract's confidence. tr-ocrtext's own fallback, when tesseract or
    pdftoppm is missing, marks nothing either; it writes <layer>.nomarks
    beside the layer instead of a form feed, which a .docx cannot hold.
    """
    if os.path.exists(txt + ".nomarks"):
        return True
    try:
        with open(txt, encoding="utf-8", errors="replace") as fh:
            return "\f" in fh.read()
    except OSError:
        return False

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
    # Court actors and document furniture. odv. and izv. appear in almost
    # every criminal file; zap. is the "Zap. št." column heading the fixture
    # spreadsheet already uses.
    "odv", "izv", "zap", "sod", "tož", "obd", "ovad", "pooblašč",
    "pril", "vlož", "fasc", "tel", "faks", "sob", "nasl", "obr",
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

# Slovene spaces its abbreviations more often than not: "d. o. o." rather
# than "d.o.o.", and likewise "s. p.", "t. i.", "l. r.". ABBREV held only the
# unspaced forms, so the spaced ones shattered a sentence one letter at a
# time -- "Družba PRIMER d. o. o. je vložila pritožbo" came out as four
# segments, three of them a single letter. A company suffix appears in
# nearly every corporate document, so this was not an edge case; each
# fragment became a reviewer unit and a memory entry, against invariant 3.
#
# Lowercase only. A capital letter before a period is an initial in a name,
# which _INITIAL_RE already holds, and treating "J." the same way here would
# be redundant.
_SPACED_ABBR_RE = re.compile(r"(?:\b[a-zčšžćđ]\.\s+)*\b[a-zčšžćđ]\.$")
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
                or _INITIAL_RE.search(tail) or _NUMBERED_RE.search(tail)
                or _SPACED_ABBR_RE.search(tail)):
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

    The kit's own file is the base layer. These are regular expressions
    maintained in the repository, not curated per-installation data: the
    pattern that matched every short all-caps word, so SKLEP and DA passed
    through untranslated, was fixed in the kit. Had the kit's copy only ever
    been seeded into a container, that fix would have reached no existing
    matter. _shared and the project add to it; neither replaces it.
    """
    global _NONTRANS_CACHE
    if _NONTRANS_CACHE is None:
        kit = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "glossary", "nontranslatable.txt")
        files = [kit, shared("glossary", "nontranslatable.txt")]
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

# ----------------------------------------------------------- citation gate

# The model completes provisions it knows by heart. Asked to translate a
# source that stops short of the famous continuation, it supplies the rest:
# measured at 2 of 10 well-known provisions, and both failures were ECHR
# article 6 -- the most quoted text in criminal procedure. The addition reads
# perfectly, contains no number, no glossary term and no non-translatable
# fragment, so nothing deterministic can see it. It is an interpretation
# presented as a translation.
#
# What IS deterministic is the condition: the source citing a statute or
# treaty. Flagging that costs nothing and cannot miss an explicit citation,
# which makes it a cheap gate for an expensive check -- an audit pass on the
# flagged fraction rather than the whole corpus. Measured, that is the
# difference between roughly +2% and +400%.
#
# The blind spot is stated rather than hidden: a famous provision paraphrased
# with no citation marker is not flagged. This bounds the risk; it does not
# remove it.

_CITE_RE = re.compile(
    r"""(
        \bčl\.|\bčlen\w*|\bodst\.|\bodstav\w*|\btočk\w*|\balinej\w*
      | \bUstav\w*|\bEKČP\b|\bEKPČ\b|\bKonvencij\w*
      | \b(?:KZ|ZKP|ZPP|ZUP|ZIZ|ZUS|ZDR|ZGD|ZPIZ|ZDavP|ZFPPIPP|ZASP|OZ|SPZ)\b(?:-\d+[A-Z]?)?
      | \bUradni\s+list\b|\bUr\.\s?l\.
    )""",
    re.IGNORECASE | re.VERBOSE)


def cites(text):
    """Distinct citation markers in a source segment."""
    return sorted({m.group(0) for m in _CITE_RE.finditer(text or "")},
                  key=str.lower)


def flagged(text):
    """True when a segment cites a statute or treaty, and so warrants the
    word-by-word check. High recall by design: a segment flagged unnecessarily
    costs a reviewer seconds, one missed puts an interpretation into a
    certified translation."""
    return bool(_CITE_RE.search(text or ""))


# ------------------------------------------------ institutions, first mention

# The translator wants an institution's source name kept beside the
# translation on its first mention in a document, and the translation alone
# thereafter: easier to delete something once than to hunt for the place it
# is missing.
#
# Per DOCUMENT, not per run, and the reason is the reader rather than the
# code. Whoever picks up the deliverable has no particular order in mind and
# may open any file first, so each has to stand on its own. Bracketing once
# across a whole matter would leave most documents referring to a definition
# in some other file the reader may never open -- and maintaining those
# cross-references would be worse than the problem it solved.
#
# Deliberately NOT done by the model. The memory keys on source text, so a
# sentence carrying the first mention would be cached with its brackets and
# reused in the next document, where the same sentence is the fortieth
# mention. Bracketing is document-scoped; the cache is corpus-scoped. A
# deterministic pass over the translated text keeps them from fighting, and
# has the side benefit of being reproducible.

_INST_CACHE = None


def institutions(direction="sl-en"):
    """(source form, target form) pairs for a direction: kit, then overlays."""
    global _INST_CACHE
    if _INST_CACHE is None:
        _INST_CACHE = {}
        kit = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "glossary", "institutions.tsv")
        files = [kit, shared("glossary", "institutions.tsv")]
        if ROOT and os.path.isdir(ROOT):
            files.append(path("glossary", "institutions.tsv"))
        for f in files:
            if not os.path.exists(f):
                continue
            for ln in open(f, encoding="utf-8"):
                ln = ln.split("#")[0].rstrip("\n")
                cols = [c.strip() for c in ln.split("\t")]
                if len(cols) >= 3 and cols[0] and cols[1]:
                    _INST_CACHE.setdefault(cols[2], []).append((cols[0], cols[1]))
    # Longest target first: "District Court in Ljubljana" must win over any
    # shorter entry that is a prefix of it.
    return sorted(_INST_CACHE.get(direction, []),
                  key=lambda p: len(p[1]), reverse=True)


class FirstMention:
    """Brackets the first mention of each institution, per document.

    One instance per document. Feed it each translated segment in order and
    it returns the segment to write, having added the source form in
    parentheses the first time that institution appears and left every later
    occurrence alone.

    Matches on what the model actually produced. If it renders an institution
    differently from the table, nothing is bracketed -- a missing bracket is
    an omission a reviewer can see and fix, a wrong one reads as correct and
    would not be looked at again.
    """

    def __init__(self, direction="sl-en"):
        self.pairs = institutions(direction)
        self.seen = set()

    def apply(self, text, reference=False):
        """text with its first mentions bracketed. With reference, text is a
        translator's rendering or a REF_OPTIONS choice among several: written
        as it is -- bracketing edited their words, and only the first option
        -- while an institution it names counts as mentioned."""
        if not text or not self.pairs:
            return text
        if reference:
            self.seen.update(tgt for _src, tgt in self.pairs if tgt in text)
            return text
        for src_form, tgt_form in self.pairs:
            if tgt_form in self.seen:
                continue
            i = text.find(tgt_form)
            if i < 0:
                continue
            # Already bracketed by hand, or the source form is right there?
            # Leave it; do not double up.
            window = text[max(0, i - len(src_form) - 4):i]
            if src_form in window or text[i:i + len(tgt_form) + 2].endswith("("):
                self.seen.add(tgt_form)
                continue
            text = (text[:i] + f"{src_form} ({tgt_form})"
                    + text[i + len(tgt_form):])
            self.seen.add(tgt_form)
        return text


# ------------------------------------------------------- locale conversion

# Dates, amounts and times are converted to the target locale rather than
# reproduced verbatim -- the translator's rule. Inside a sentence the model
# does it, instructed by the prompt. A segment that is ONLY a date, a time or
# an amount never reaches the model: localize() converts it first. It was
# once returned untouched, because is_translatable() is false for it, so a
# spreadsheet Datum column stayed in Slovene form while the same date in
# prose became English, and the deliverable contradicted itself column by
# column. And is_translatable() is true for March 5, 2024 or 2:30 p.m., which
# have letters, so asking it first sent those to the model.
#
# Doing it here instead of sending these to the model is also ~48 s per
# unique value cheaper, and deterministic: the same input always yields the
# same output, which a language model does not guarantee.

_EN_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December")

# Lowercase, and that is not a stylistic choice: Slovene does not capitalise
# month names. "5. Marec 2024" is wrong twice over.
_SL_MONTHS = ("januar", "februar", "marec", "april", "maj", "junij", "julij",
              "avgust", "september", "oktober", "november", "december")

_DATE_DMY = re.compile(r"^\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\.?\s*$")
# English month-name dates, both orders. Numeric forms like 03/05/2024 are
# deliberately not matched: which number is the month is unknowable, and
# guessing would silently move a date by months.
_DATE_EN = re.compile(
    r"^\s*(?:(" + "|".join(_EN_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"
    r"|(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(_EN_MONTHS) + r"),?\s+(\d{4}))\s*\.?\s*$",
    re.IGNORECASE)
_TIME_HM = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
_TIME_AMPM = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*([ap])\.?\s*m\.?\s*$", re.I)
# A Slovene date with its month named, in either case a date takes:
# 5. marec 2024, 5. marca 2024.
_SL_MONTH_FORMS = {name: i for i, names in enumerate(zip(
    _SL_MONTHS, ("januarja", "februarja", "marca", "aprila", "maja", "junija",
                 "julija", "avgusta", "septembra", "oktobra", "novembra",
                 "decembra")), 1) for name in names}
_DATE_SL_NAMED = re.compile(
    r"^\s*(\d{1,2})\.\s*(" + "|".join(_SL_MONTH_FORMS) + r")\s+(\d{4})\.?\s*$", re.I)
_SL_DECIMAL = re.compile(r"^(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?$")
_EN_DECIMAL = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")
# An English number that reads as well as a section or clause, a version or
# a time as it does as a decimal: 5.10, 3.2, 14.30. Up to three digits with
# no leading zero, one or two after the point, no thousands separator.
_AMBIGUOUS_POINT = re.compile(r"[1-9]\d{0,2}\.\d{1,2}")


def _sl_number_to_en(s):
    """12.450,00 -> 12,450.00. Slovene groups with '.' and decimates with ','."""
    if not _SL_DECIMAL.fullmatch(s):
        return None
    return s.replace(".", "\x00").replace(",", ".").replace("\x00", ",")


def _en_number_to_sl(s):
    """12,450.00 -> 12.450,00."""
    if not _EN_DECIMAL.fullmatch(s):
        return None
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _sl_to_en(s):
    m = _DATE_DMY.match(s)
    named = None if m else _DATE_SL_NAMED.match(s)
    m = m or named
    if m:
        d, y = int(m.group(1)), m.group(3)
        mo = _SL_MONTH_FORMS[m.group(2).lower()] if named else int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            # "March 5, 2024" -- the form the translator specifies for
            # English. Not "5 March 2024": that was this file's own invention
            # and it was wrong.
            return f"{_EN_MONTHS[mo - 1]} {d}, {y}"
        return None

    m = _TIME_HM.match(s)
    if m:
        h, mi = int(m.group(1)), m.group(2)
        if 0 <= h <= 23 and 0 <= int(mi) <= 59:
            return f"{h % 12 or 12}:{mi} {'a.m.' if h < 12 else 'p.m.'}"
        return None

    return _decorated(s, lambda number, _m: _sl_number_to_en(number))


def _en_to_sl(s):
    m = _DATE_EN.match(s)
    if m:
        if m.group(1):                       # "March 5, 2024"
            name, d, y = m.group(1), int(m.group(2)), m.group(3)
        else:                                # "5 March 2024"
            d, name, y = int(m.group(4)), m.group(5), m.group(6)
        mo = [n.lower() for n in _EN_MONTHS].index(name.lower())
        if 1 <= d <= 31:
            # "5. marec 2024": the period marks an ordinal -- bare "5" would
            # read as the cardinal number, not the fifth day -- and the month
            # is lowercase, which Slovene requires.
            #
            # Nominative, deliberately. Running text often inflects to the
            # genitive ("dne 5. marca 2024"), but "dne" has several tricky
            # uses and this converter only ever sees a whole-segment date with
            # no sentence around it to judge from. The translator reviews the
            # draft regardless, so a stiff-reading date is cheap; guessing the
            # case from no context would not be.
            return f"{d}. {_SL_MONTHS[mo]} {y}"
        return None

    m = _TIME_AMPM.match(s)
    if m:
        h, mi, ap = int(m.group(1)), m.group(2), m.group(3).lower()
        if 1 <= h <= 12 and 0 <= int(mi) <= 59:
            h24 = (0 if h == 12 else h) if ap == "a" else (12 if h == 12 else h + 12)
            # 24-hour, zero-padded: formal documents write 09:05 and 00:15,
            # and a fixed width keeps a table column readable.
            return f"{h24:02d}:{mi}"
        return None

    return _decorated(s, _comma_decimal)


# Capitalised: German capitalises nouns, month names among them.
_DE_MONTHS = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
              "August", "September", "Oktober", "November", "Dezember")


def _en_to_de(s):
    """English whole-segment values in the form used in Germany.

    "5. März 2024": the day takes an ordinal period, as in Slovene, but the
    month is capitalised and there is no need to guess a grammatical case.
    Times go to the 24-hour clock, zero-padded like the Slovene form, and
    without "Uhr": a cell holding only a time is a column value, and adding
    a word to it is a choice for the translator rather than this converter.
    Amounts group and decimate exactly as Slovene does, 12.450,00, so the
    Slovene number conversion is the German one.
    """
    m = _DATE_EN.match(s)
    if m:
        if m.group(1):                       # "March 5, 2024"
            name, d, y = m.group(1), int(m.group(2)), m.group(3)
        else:                                # "5 March 2024"
            d, name, y = int(m.group(4)), m.group(5), m.group(6)
        mo = [n.lower() for n in _EN_MONTHS].index(name.lower())
        if 1 <= d <= 31:
            return f"{d}. {_DE_MONTHS[mo]} {y}"
        return None

    m = _TIME_AMPM.match(s)
    if m:
        h, mi, ap = int(m.group(1)), m.group(2), m.group(3).lower()
        if 1 <= h <= 12 and 0 <= int(mi) <= 59:
            h24 = (0 if h == 12 else h) if ap == "a" else (12 if h == 12 else h + 12)
            return f"{h24:02d}:{mi}"
        return None

    return _decorated(s, _comma_decimal)


# Switzerland writes German by the Swiss Federal Chancellery's Schreibweisungen
# (2015 edition). Where they differ from Germany in a way a deliverable shows:
#
#   numbers   a decimal comma, 3,5; from five digits the thousands separated
#             by a non-breaking space, 12 450; four digits written together,
#             1250. The apostrophe, 12'450, is no longer recommended (§512)
#   money     a decimal point and the currency code first: CHF 1250.50,
#             EUR 12 450.00; a whole number of francs is Fr. 20.– (§540-546)
#   times     a period and no leading zero: 9.05, 14.30 (§533)
#   spelling  ss, never ß
#
# Dates are written as in Germany, 2. September 2006 (§535).
#
# A number is money only beside a currency, the translator's rule. A
# converter sees the number and not the column it stands in, so a bare
# 12,450.00 becomes 12 450,00, which cannot be misread even where it was
# money. As in Germany, a time on its own gets no "Uhr".

NBSP = "\u00a0"
# A word joiner: no width, and no line break on either side of it.
WJ = "\u2060"
_CURRENCY = r"CHF|Fr\.|EUR|USD|GBP|SIT|€|\$|£"
# A value and what may stand around its number: a currency before or after
# it, a sign, accounting brackets, a percent sign -- $1,000, -1,250.00,
# (1,250.00), € 12.450,00, 12.5%. Outside Switzerland what stands around the
# number is kept as written.
_VALUE = re.compile(
    rf"^(?P<open>\(\s*)?(?P<sign>[-−+]\s*)?(?:(?P<pre>{_CURRENCY})\s*)?"
    rf"(?P<sign2>[-−+])?(?P<num>\d[\d.,]*?)"
    rf"(?:\s*(?:(?P<post>{_CURRENCY})|(?P<pct>%)))?(?P<close>\s*\))?$")


def _value_match(s):
    m = _VALUE.match(s)
    return m if m and bool(m.group("open")) == bool(m.group("close")) else None


def _quantity(m):
    """Does what stands beside the number make it a quantity: a currency, a
    sign or a percent? Brackets alone do not: (3.2) is a clause as often."""
    return any(m.group(g) for g in ("pre", "post", "pct", "sign", "sign2"))


def _decorated(s, convert):
    """s with its number converted by convert(number, match), and what stands
    around it kept; None if s is not a value, or convert() gives None."""
    m = _value_match(s)
    number = m and convert(m.group("num"), m)
    return s[:m.start("num")] + number + s[m.end("num"):] if number else None


def _comma_decimal(number, m):
    """An English number as Slovene and German write it, 1.234,56. Not one
    that reads as a reference or a time as well as a decimal, unless what
    stands beside it makes it a quantity."""
    if _AMBIGUOUS_POINT.fullmatch(number) and not _quantity(m):
        return None
    return _en_number_to_sl(number)


def _swiss_number(s, money, quantity=False):
    """An English-format number in Swiss form, or None if s is not one:
    12,450.00 as 12 450,00, or 12 450.00 when it is money; 1,250 as 1250."""
    # Bare digits with no currency, sign or percent beside them are left as
    # they stand: 80331 is as likely a postcode, an account or a file number
    # as a quantity, and an identifier is reproduced verbatim.
    if not _EN_DECIMAL.fullmatch(s) or (s.isdigit() and not (money or quantity)):
        return None
    integer, _, fraction = s.replace(",", "").partition(".")
    if len(integer) > 4:
        integer = _regroup(integer, NBSP)
    return integer + (("." if money else ",") + fraction if fraction else "")


def _en_to_ch(s):
    """English whole-segment values in Swiss form; the rules are above."""
    if _DATE_EN.match(s):
        return _en_to_de(s)                   # written as in Germany
    m = _TIME_AMPM.match(s)
    if m:
        h, mi, ap = int(m.group(1)), m.group(2), m.group(3).lower()
        if 1 <= h <= 12 and 0 <= int(mi) <= 59:
            h24 = (0 if h == 12 else h) if ap == "a" else (12 if h == 12 else h + 12)
            return f"{h24}.{mi}"
        return None
    m = _TIME_HM.match(s)
    if m:
        h, mi = int(m.group(1)), m.group(2)
        if 0 <= h <= 23 and 0 <= int(mi) <= 59:
            return f"{h}.{mi}"
        return None
    m = _value_match(s)
    if not m or (_AMBIGUOUS_POINT.fullmatch(m.group("num")) and not _quantity(m)):
        return None
    currency = m.group("pre") or m.group("post")
    number = _swiss_number(m.group("num"), money=bool(currency),
                           quantity=bool(m.group("pct") or m.group("sign")
                                         or m.group("sign2")))
    if number is None:
        return None
    if not currency:
        return s[:m.start("num")] + number + s[m.end("num"):]
    # The currency goes first, and a sign before it: -CHF 12 450.50.
    sign = (m.group("sign") or "").strip() + (m.group("sign2") or "")
    integer, _, fraction = number.partition(".")
    if currency in ("CHF", "Fr.") and not fraction.strip("0"):
        amount = f"Fr.{NBSP}{integer}.{WJ}–"     # one line: _whole_francs()
    else:
        amount = f"{currency} {number}"
    return ("(" if m.group("open") else "") + sign + amount + (")" if m.group("close") else "")


_SHARP_S = re.compile(r"\w*[ßẞ]\w*")


def swiss_spelling(source, text):
    """text with ß written ss and ẞ written SS, the Swiss way -- except in a
    word the source has too.

    A name or an address is reproduced verbatim, and some carry ß: where the
    source says Strauß, so does the draft, while a word the draft translated
    is converted.
    """
    keep = set(_SHARP_S.findall(source or ""))

    def swap(m):
        word = m.group(0)
        if word in keep:
            return word
        upper = word.replace("ß", "").isupper()
        return word.replace("ẞ", "SS").replace("ß", "SS" if upper else "ss")

    return _SHARP_S.sub(swap, text or "")


def localize(text, src_lang, tgt_lang):
    """Convert a whole-segment date, time or amount to the target locale.

    Slovene writes "5. marec 2024" -- ordinal period after the day, month
    lowercase, spaces between all three. English writes "March 5, 2024".
    Neither "5 March 2024" nor "5. Marec 2024" is correct in either language.

    Returns the text unchanged when nothing applies, and for every pair other
    than sl<->en, en->de and en->de-CH. German writes "5. März 2024" and keeps
    the 24-hour clock, so it has its own rules, and Swiss German differs from
    it again in numbers, money and times (see above); other German pairs are
    left alone until someone needs them, because applying another language's
    conventions silently would be worse than doing nothing.

    Deliberately conservative in three places. "14:30" is read as a time,
    "14.30" never is. From English, a number like 5.10, 3.2 or 14.30 standing
    alone is not converted at all: it is as likely a section, a clause or a
    time as a decimal, and 5,10 would turn a reference into a quantity. A
    wrong guess corrupts a value where leaving it misformats one. With a
    currency beside it, or a thousands separator in it, it is converted.
    An all-numeric date like 03/05/2024 is left alone in both directions,
    because which number is the month cannot be known and guessing would move
    the date by months.

    A value may carry a currency on either side, a sign, accounting brackets
    or a percent sign, each kept with it: -1,250.00 into German is -1.250,00,
    and $1,000 is $1.000. Two values joined by a dash are a range, and each
    end is converted: 12:00–13:00 into English is 12:00 p.m.–1:00 p.m.
    """
    local = _local_value(text, src_lang, tgt_lang)
    return text if local is None else local


_CONVERTERS = {("sl", "en"): _sl_to_en, ("en", "sl"): _en_to_sl,
               ("en", "de"): _en_to_de, ("en", "de-CH"): _en_to_ch}
_RANGE = re.compile(r"^(\S.*?)(\s*[–-]\s*)(\S.*)$")


def _local_value(text, src_lang, tgt_lang):
    """What localize() makes of a segment that is a date, a time or an amount
    -- the segment itself when it is already in the target's form -- or None
    when it is no such value, or one this pair leaves alone."""
    s = (text or "").strip()
    convert = _CONVERTERS.get((src_lang, tgt_lang))
    if not s or convert is None:
        return None
    local = convert(s)
    if local is None:
        m = _RANGE.match(s)
        ends = m and (convert(m.group(1)), convert(m.group(3)))
        # Both ends, and one of them changed: 2024-03-05 is no range.
        if ends and None not in ends and ends != (m.group(1), m.group(3)):
            local = ends[0] + m.group(2) + ends[1]
    return local


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

# ------------------------------------------- comparing numbers across a pair

# Locale conversion is CORRECT output, not an error. Slovene writes dates
# 5. 3. 2024 or 5. marec 2024, decimals with a comma, and time on a 24-hour
# clock; English writes March 5, 2024, decimals with a point, and 2:30 p.m.
# The translator requires those conversions, so the numerals legitimately
# move around -- a month becomes a word, an hour shifts by twelve.
#
# Comparing raw digits therefore raised a tr-lint NUM finding for every date
# in the corpus, burying the real ones. Both sides are canonicalised first so
# the comparison is of values rather than spellings. It lives here rather
# than in tr-lint because reference alignment needs the same answer to "do
# these two sentences carry the same numbers", and two copies of that rule
# would drift the way every other duplicated rule in this kit has.
NUM_RE = re.compile(r"\d[\d.,:/–-]*\d|\d")
MONTHS = {
    1: ("january", "januar", "januarja", "jan"),
    2: ("february", "februar", "februarja", "feb"),
    3: ("march", "marec", "marca", "mar", "märz"),
    4: ("april", "aprila", "apr"),
    5: ("may", "maj", "maja", "mai"),
    6: ("june", "junij", "junija", "jun", "juni"),
    7: ("july", "julij", "julija", "jul", "juli"),
    8: ("august", "avgust", "avgusta", "aug"),
    9: ("september", "septembra", "sep", "sept"),
    10: ("october", "oktober", "oktobra", "oct", "okt"),
    11: ("november", "novembra", "nov"),
    12: ("december", "decembra", "dec", "dezember"),
}
_MONTH_NAMES = "|".join(sorted((n for names in MONTHS.values() for n in names),
                               key=len, reverse=True))
# A month name counts only beside a number. "May" is also the commonest modal
# verb in English legal drafting -- "the court may order" -- and read as the
# fifth month it put a 5 into every such sentence, which tr-lint reported as
# a number the translation had lost. A date always has a number beside its
# month: "March 5", "5 March", "5th March", "5. marec", "20. Mai", "May 2024".
_BESIDE_A_NUMBER = (
    r"(?:(?<=\d )|(?<=\d\. )|(?<=\d\.)|(?<=\dst )|(?<=\dnd )|(?<=\drd )"
    r"|(?<=\dth ))({names})\b|\b({names})(?=\.?,?\s+\d)")
_MONTH_RE = re.compile(_BESIDE_A_NUMBER.format(names=_MONTH_NAMES), re.I)
# English writes a month capitalised, and in English only a month written so
# counts: read in any case, "Paragraph 2 may be applied" was May and put a 5
# into the sentence. Slovene writes its months in lower case, so elsewhere
# any case counts.
_EN_MONTH_NAMES = "|".join(sorted(
    {w for name in _EN_MONTHS + ("Sept",) for w in (name, name[:3])}
    | {w.upper() for name in _EN_MONTHS + ("Sept",) for w in (name, name[:3])},
    key=len, reverse=True))
_EN_MONTH_RE = re.compile(_BESIDE_A_NUMBER.format(names=_EN_MONTH_NAMES))
_MONTH_NUM = {n: str(num) for num, names in MONTHS.items() for n in names}

# 2:30 p.m. / 2:30PM / 12:05 a.m.
_AMPM_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*([ap])\.?\s*m\.?", re.I)


def _to24(m):
    h, mm, ap = int(m.group(1)), m.group(2), m.group(3).lower()
    if ap == "a":
        h = 0 if h == 12 else h
    else:
        h = 12 if h == 12 else h + 12
    return f"{h:02d}:{mm}"


# A time is one value whether written 14:30 or 14.30, as Switzerland writes
# it: both become 14.30, which a period time on the other side then matches.
_CLOCK = re.compile(r"(?<![\d:.])(\d{1,2}):([0-5]\d)(?![\d:])")


# Digit groups written apart are one number: 12 450 with a non-breaking or a
# thin space, and 12'450, which older Swiss documents use. A plain space joins
# groups only in Swiss German, whose prompt asks for them and whose model
# writes them with plain spaces; elsewhere "Items 100 200 300" is three
# numbers. A whole franc amount, Fr. 20.–, is 20.00. Without these, a Swiss
# draft that carried 12,450.00 over correctly as 12 450.00 would raise a NUM
# finding and a firmer retry. The look-arounds keep a street number beside a
# postcode apart: "Bahnhofstrasse 12 8001" has no group of exactly three
# digits after the 12.
_GROUPED = re.compile(
    r"(?<![\d.,'’])(\d{1,3})((?:[\u00a0\u202f\u2009'’]\d{3})+)(?!\d)")
_GROUPED_SWISS = re.compile(
    r"(?<![\d.,'’])(\d{1,3})((?:[ \u00a0\u202f\u2009'’]\d{3})+)(?!\d)")
_WHOLE_AMOUNT = re.compile(r"(\d)[.,]\u2060?[–-](?!\d)")


# A date is one value however it is written. 5.3.2024, 5. 3. 2024,
# 05.03.2024, 2024-03-05, March 5, 2024, 5th March 2024, 5. marec 2024 and
# 5. März 2024 all fold to 20240305 before digits are compared. Compared digit
# by digit, a correctly converted date was three numbers the source did not
# have -- 3, 5 and 2024 against 532024 -- so every compact date the model
# converted earned a firmer retry, and a retry that copied the source's
# spelling won it for adding fewer.
_DATE_DOTTED = re.compile(r"(?<![\d.])(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})(?!\d)")
_DATE_ISO = re.compile(r"(?<![\d./-])(\d{4})-(\d{2})-(\d{2})(?![\d-])")
_DATE_MONTH_FIRST = re.compile(
    r"\b(" + _MONTH_NAMES + r")\b\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b,?\s+(\d{4})(?!\d)",
    re.I)
_DATE_DAY_FIRST = re.compile(
    r"(?<![\d.])(\d{1,2})(?:st|nd|rd|th|\.)?\s*(?:of\s+)?(" + _MONTH_NAMES
    + r")\b\.?,?\s+(\d{4})(?!\d)", re.I)


def _date_value(y, mo, d):
    """A date as one run of digits, spaced off so that it joins no number
    beside it; None when the parts cannot be a date."""
    y, mo, d = int(y), int(mo), int(d)
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f" {y:04d}{mo:02d}{d:02d} "


# A date written with slashes is day first in one country and month first in
# another, and nothing in 03/05/2024 says which. It folds to both readings,
# 20240305/20240503, which agree with either on the other side -- see
# number_gap() -- so a translation may make it 5 March or May 3, but not
# 7 March. Where one reading is no date, as in 03/15/2024, it is the other.
_DATE_SLASHED = re.compile(r"(?<![\d./])(\d{1,2})/(\d{1,2})/(\d{4})(?![\d/])")
_EITHER_DATE = re.compile(r"\d{8}/\d{8}")


def _either_date(m):
    a, b, y = m.groups()
    readings = sorted({r.strip() for r in (_date_value(y, b, a), _date_value(y, a, b))
                       if r})
    return f" {'/'.join(readings)} " if readings else m.group(0)


def _fold_dates(s):
    month = lambda name: _MONTH_NUM[name.lower()]   # noqa: E731
    s = _DATE_SLASHED.sub(_either_date, s)
    s = _DATE_ISO.sub(lambda m: _date_value(*m.groups()) or m.group(0), s)
    s = _DATE_DOTTED.sub(
        lambda m: _date_value(m.group(3), m.group(2), m.group(1)) or m.group(0), s)
    s = _DATE_MONTH_FIRST.sub(
        lambda m: _date_value(m.group(3), month(m.group(1)), m.group(2))
        or m.group(0), s)
    return _DATE_DAY_FIRST.sub(
        lambda m: _date_value(m.group(3), month(m.group(2)), m.group(1))
        or m.group(0), s)


def canon_locale(s, lang=None):
    """Fold locale spellings onto one form before numbers are compared. Given
    lang, a.m. and p.m. are read only in English -- in German, "um 12:00 am
    Montag" is on Monday, not after midnight -- and an English month name only
    capitalised."""
    s = _fold_dates(s or "")
    s = _WHOLE_AMOUNT.sub(r"\1.00", s)               # Fr. 20.– -> 20.00
    grouped = _GROUPED_SWISS if lang == "de-CH" else _GROUPED
    s = grouped.sub(lambda m: m.group(1) + re.sub(r"\D", "", m.group(2)), s)
    if lang in (None, "en"):
        s = _AMPM_RE.sub(_to24, s)                   # 2:30 p.m. -> 14:30
    s = _CLOCK.sub(r"\1.\2", s)                      # 14:30 -> 14.30
    months = _EN_MONTH_RE if lang == "en" else _MONTH_RE
    return months.sub(                               # March 5 -> 3 5
        lambda m: _MONTH_NUM[(m.group(1) or m.group(2)).lower()], s)


def _value(token, lang):
    """One number from canon_locale()'s text as a value. 12,450.00 in English
    and 12.450,00 in German are both 12450, 1.50 and 1,50 are both 1.50, and
    an all-zero decimal part is dropped, so 20, 20.00 and Fr. 20.– agree.

    Read in lang's notation, because the same digits are different numbers:
    1,250 is 1250 in English and 1.25 in German. English decimates with a
    point and groups with a comma, Slovene and German the other way round,
    and Swiss German decimates with either and never groups with a point.
    Where both marks appear, the later one is the decimal in any language.
    Without lang, and for an identifier, a range or a case number, only the
    digits count -- which read 12.5 and 125 as one number."""
    if _EITHER_DATE.fullmatch(token):
        return token
    if lang is None or not re.fullmatch(r"\d+(?:[.,]\d+)*", token):
        if lang is None:
            token = re.sub(r"[.,]0{1,2}$", "", token)
        digits = re.sub(r"\D", "", token)
        return (digits.lstrip("0") or "0") if digits else None
    dots, commas = token.count("."), token.count(",")
    if dots and commas:
        mark = "." if token.rfind(".") > token.rfind(",") else ","
    elif not (dots or commas):
        mark = None
    else:
        sep = "." if dots else ","
        parts = token.split(sep)
        if len(parts) > 2:
            mark = None       # grouped, 1.234.567; or a 1.2.3 section, digits alone
        elif lang == "de-CH" or (sep == ".") == (base_lang(lang) == "en"):
            mark = sep        # the language's own decimal mark
        else:
            mark = None if len(parts[1]) == 3 else sep
    if mark is None:
        return re.sub(r"\D", "", token).lstrip("0") or "0"
    whole, _, fraction = token.rpartition(mark)
    whole = re.sub(r"\D", "", whole).lstrip("0") or "0"
    return f"{whole}.{fraction}" if fraction.strip("0") else whole


def norm_nums(s, lang=None):
    """The numbers in s as values, with dates and times folded onto one form
    each: see canon_locale() and _value(). Give lang wherever it is known --
    the source's language for the source, the target's for a draft."""
    out = collections.Counter()
    for token in NUM_RE.findall(canon_locale(s, lang)):
        value = _value(token, lang)
        if value:
            out[value] += 1
    return out


def number_gap(s, t):
    """(lost, added) between two norm_nums() counts: what s has and t lacks,
    and what t has and s lacks. A slashed date agrees with either reading."""
    if any("/" in k for k in s) or any("/" in k for k in t):
        s, t = s.copy(), t.copy()
        for mine, theirs in ((s, t), (t, s)):
            for either in [k for k in mine if "/" in k]:
                for reading in either.split("/"):
                    n = min(mine[either], theirs[reading] - mine[reading])
                    if n > 0:
                        mine[either] -= n
                        mine[reading] += n
    return s - t, t - s


def same_numbers(s, t):
    """Do two norm_nums() counts carry the same numbers?"""
    return s == t or not any(number_gap(s, t))


def compare_numbers(src, tgt, src_lang=None, tgt_lang=None):
    """(lost, added): the source's numbers the target lacks, and the target's
    the source lacks, each side read in its own language. What tr-lint's NUM
    check reports, and what the invention retry and reference alignment test."""
    return number_gap(norm_nums(src, src_lang), norm_nums(tgt, tgt_lang))


def nontranslatable_kept(frag, tgt, src_lang, tgt_lang):
    """Did a fragment the source must keep reach tgt? Verbatim, or converted
    as localize() converts it; into Swiss German also in the forms its
    conventions allow -- CHF written Fr., and an amount whose value and
    currency the draft keeps however it spells them: 12,450.00 CHF as
    CHF 12 450.00 or Fr. 12 450.–."""
    if frag in tgt:
        return True
    want = localize(frag, src_lang, tgt_lang)
    if want != frag and want in tgt:
        return True
    if tgt_lang != "de-CH":
        return False
    francs = lambda text: re.sub(r"\bCHF\b", "Fr.", text)   # noqa: E731
    if francs(frag) in francs(tgt):
        return True
    return (want != frag and not compare_numbers(frag, tgt, src_lang, tgt_lang)[0]
            and all(francs(c) in francs(tgt) for c in re.findall(_CURRENCY, frag)))

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
    terms = sorted(merged.items())
    # A Swiss project's terms in Swiss spelling, so the prompt shows the model
    # ss and tr-lint checks for it. A term's own source form stands in for the
    # source sentence: an entry with ß on both sides, such as a name, keeps it.
    if _env_target() == "de-CH":
        terms = [(term, swiss_spelling(term, target)) for term, target in terms]
    return terms

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

def _key(src, direction, gloss_sig=""):
    """Cache identity for a segment.

    gloss_sig is the glossary block that applied to THIS segment, not the
    whole glossary. Without it in the key, adding a term and re-running
    changed nothing: every affected segment was served from cache under the
    old rendering, so the one mechanism the kit has for terminology
    consistency did nothing on any document already translated. The manual
    said re-running after a glossary edit was cheap because the memory
    reuses segments -- which was true, and was exactly the reason the edit
    had no effect.

    Keyed on the applicable terms rather than the whole file so that adding
    a banking term does not invalidate a corpus of criminal-procedure
    segments it never touches.
    """
    # The model and prompt version routed for THIS direction, not the
    # project's. A worker can be pointed at another pair with --from/--to,
    # and its segments must not be filed under the project's model.
    s, t = split_direction(direction)
    model, version = model_for(s, t), prompt_version(s, t)
    h = hashlib.sha256()
    if gloss_sig:
        h.update(f"{direction}\x00{model}\x00{version}\x00{gloss_sig}"
                 f"\x00{src}".encode())
    else:
        # No applicable glossary terms: hash exactly as this function did
        # before the glossary was part of the key, so rows written then are
        # still reachable.
        #
        # Adding the field unconditionally silently orphaned an entire
        # memory. The extra separator changed the digest even when the
        # glossary contributed nothing, so 532 already-translated segments
        # became invisible to tr-run, tr-lint and tr-terms at once -- not
        # reported as missing, just gone, which is the worst way for a cache
        # to fail. Found because tr-terms said "no segments for prompt v5"
        # over a memory that held 532 of them.
        h.update(f"{direction}\x00{model}\x00{version}\x00{src}".encode())
    return h.hexdigest()

def tm_current_key(src, direction, gloss):
    """The key tr-run would use for this segment right now.

    tr-lint needs it to tell "the row tr-run will reuse today" from "a row
    left behind by an earlier glossary". Without that distinction, editing
    one term makes every segment it touches appear twice and report as
    INCON -- the same false alarm that prompt-version bumps used to cause,
    in a new disguise.
    """
    return _key(src, direction, glossary_block(src, gloss or []))


def tm_get(src, direction, gloss_sig=""):
    db = _db()
    r = db.execute("SELECT tgt FROM tm WHERE key=?",
                   (_key(src, direction, gloss_sig),)).fetchone()
    db.close()
    return r[0] if r else None

def tm_put(src, tgt, direction, gloss_sig=""):
    s, t = split_direction(direction)
    db = _db()
    db.execute("INSERT OR REPLACE INTO tm VALUES(?,?,?,?,?,?,?)",
               (_key(src, direction, gloss_sig), src, tgt, direction,
                model_for(s, t), prompt_version(s, t), time.time()))
    db.commit(); db.close()

# ---------------------------------------------------------------- model

LANG = {"sl": "Slovene", "en": "English", "de": "German"}

# Rules that differ by language live in blocks inside the one prompt file:
#
#     {when TGT=de}
#     - Convert dates ... 5. März 2024 ...
#     {end}
#
# Conditions test SRC, TGT, VARIANT or PAIR against comma-separated values,
# several on one line must all hold, and the marker lines themselves are
# never sent. TGT and PAIR name the language, so a rule for de reaches de-CH
# too; VARIANT is DE for Germany, plain de included, or CH, or AT.
# One file for every pair, rather than a file per pair, because the rules
# that do not vary -- OCR_ILLEGIBLE, what is verbatim, the register -- would
# otherwise be written out several times and drift, which is how the second
# prompt copy this file replaced came to exist.
#
# It also keeps each call short. Prefill is most of a segment's cost, and a
# Slovene->English call has no use for the German rules.
_WHEN_RE = re.compile(r"^\{when\s+([^}]*)\}$")
_END_RE = re.compile(r"^\{end\}$")
_WHEN_VALUES = {
    "SRC": set(LANG), "TGT": set(LANG),
    "VARIANT": {v for vs in VARIANTS.values() for v in vs},
    "PAIR": {f"{a}-{b}" for a in LANG for b in LANG if a != b},
}


def _select_blocks(text, src_lang, tgt_lang, where):
    """The prompt text that applies to this pair, markers removed."""
    lang = base_lang(tgt_lang)
    variant = tgt_lang.partition("-")[2] or VARIANTS.get(lang, ("",))[0]
    facts = {"SRC": src_lang, "TGT": lang, "VARIANT": variant,
             "PAIR": f"{src_lang}-{lang}"}
    out, keep, opened = [], True, 0
    for n, line in enumerate(text.splitlines(keepends=True), 1):
        m = _WHEN_RE.match(line.strip())
        if m:
            if opened:
                sys.exit(f"{where}:{n}: {{when}} inside the block opened at "
                         f"line {opened}; close it with {{end}} first")
            opened, keep = n, True
            for cond in m.group(1).split():
                k, _, vals = cond.partition("=")
                k = k.upper()
                if k not in facts or not vals:
                    sys.exit(f"{where}:{n}: cannot read {cond!r} - write "
                             f"SRC=, TGT=, VARIANT= or PAIR=, e.g. "
                             f"{{when TGT=de VARIANT=CH}}")
                # Read in any case, and refused when a value names nothing:
                # {when TGT=fr} or {when VARIANT=ch} dropped its block for
                # every pair without a word.
                spell = str.upper if k == "VARIANT" else str.lower
                wanted = {spell(v) for v in vals.split(",")}
                unknown = sorted(wanted - _WHEN_VALUES[k])
                if unknown:
                    sys.exit(f"{where}:{n}: {k}={','.join(unknown)} names nothing "
                             f"this kit knows - {k} takes "
                             f"{', '.join(sorted(_WHEN_VALUES[k]))}")
                keep = keep and facts[k] in wanted
            continue
        if _END_RE.match(line.strip()):
            if not opened:
                sys.exit(f"{where}:{n}: {{end}} with no {{when}} before it")
            opened, keep = 0, True
            continue
        if keep:
            out.append(line)
    if opened:
        sys.exit(f"{where}:{opened}: {{when}} is never closed with {{end}}")
    return "".join(out)


_TEMPLATES = {}


def prompt_override():
    """The file standing in for the kit's prompts/translate.txt, or None: the
    project's prompts/translate.txt, else _shared/prompts/translate.txt."""
    tpls = [shared("prompts", "translate.txt")]
    if ROOT and os.path.isdir(ROOT):                 # see load_glossary()
        tpls.append(path("prompts", "translate.txt"))   # project overrides shared
    found = [tpl for tpl in tpls if os.path.exists(tpl)]
    return found[-1] if found else None


def _prompt_template(src_lang, tgt_lang):
    """The prompt for a pair with {GLOSSARY} still in place, or None when the
    kit's file is missing. Read once per pair per process, so the text sent
    and the version derived from it cannot disagree mid-run."""
    k = (src_lang, tgt_lang)
    if k in _TEMPLATES:
        return _TEMPLATES[k]
    kit_prompt = os.path.join(KIT_DIR, "prompts", "translate.txt")
    if not os.path.exists(kit_prompt):
        return None
    where = prompt_override() or kit_prompt
    with open(where, encoding="utf-8") as fh:
        base = fh.read()
    t = _select_blocks(base, src_lang, tgt_lang, where) \
        .replace("{SRC}", LANG.get(src_lang, src_lang)) \
        .replace("{TGT}", LANG.get(base_lang(tgt_lang), tgt_lang))
    _TEMPLATES[k] = t
    return t


def build_prompt(src_lang, tgt_lang, gloss_block):
    """The kit's prompts/translate.txt, unless a project file overrides it.

    Read from the file rather than embedded here, because it was embedded
    here AND shipped as prompts/translate.txt, and nothing read the file.
    Two copies of the same text with no mechanism connecting them: they were
    byte-identical by luck, and the first edit to either would have made the
    shipped file a lie about what the model is actually told. A prompt is
    content, not code -- keeping it in one text file also makes changes to
    it reviewable as prose.

    The kit copy travels with the repository, so a correction reaches every
    project as soon as the kit is updated. case-init deliberately does not
    seed a copy into _shared: a copy there wins over this one and would
    freeze the prompt at the day the container was created, while
    TR_PROMPT_VERSION went on advancing without it. An override is still
    honoured when placed on purpose -- per matter at
    <project>/prompts/translate.txt, or across matters at
    _shared/prompts/translate.txt -- which is the case that rule exists for.
    """
    t = _prompt_template(src_lang, tgt_lang)
    if t is None:
        kit_prompt = os.path.join(KIT_DIR, "prompts", "translate.txt")
        sys.exit(f"the kit's prompt is missing: {kit_prompt}\n"
                 f"It is the source of every translation instruction. Restore "
                 f"it from the repository rather than translating without it.")
    return t.replace("{GLOSSARY}", gloss_block)


# THE PROMPT VERSION IS DERIVED FROM THE PROMPT
#
# The memory keys on it (invariant 7): anything cached under another version
# was produced under a different instruction and must not be reused. It was
# a string, TR_PROMPT_VERSION, bumped by hand on every edit -- v2 when dates
# stopped being verbatim, v3 when institution names started being
# translated, v4 when both date forms were corrected, v5 when the model was
# told to pass OCR_ILLEGIBLE through rather than judge legibility, v6 for
# short labels. Each bump invalidated every pair at once, and a forgotten one
# reused stale translations with nothing to show it.
#
# Now it is a hash of the text a pair is actually sent. Editing the German
# rules moves the version for German pairs and leaves Slovene->English
# alone; a project's own prompt override gets a version of its own; and
# forgetting to bump is no longer possible.
#
# The v6 text is kept by name. These are the hashes of the two pairs that
# were ever translated under it, so every memory row and every
# deliverables.tsv line written as "v6" still matches. TR_PROMPT_VERSION
# remains as an explicit override.
_LEGACY_PROMPT_VERSIONS = {
    "6b2f2803b65c03bb7c921031b9e1ac5a71a553abc9679b0d2e05d32b52a954ed": "v6",  # sl-en
    "0374c54664393bf75e67be73a393521f05f182d91df1fe9ab5ea79dabaeee37f": "v6",  # en-sl
}
_VERSIONS = {}


def prompt_version(src_lang, tgt_lang):
    explicit = os.environ.get("TR_PROMPT_VERSION")
    if explicit:
        return explicit
    k = (src_lang, tgt_lang)
    if k not in _VERSIONS:
        t = _prompt_template(src_lang, tgt_lang)
        if t is None:
            _VERSIONS[k] = "missing"
        else:
            h = hashlib.sha256(t.encode()).hexdigest()
            _VERSIONS[k] = _LEGACY_PROMPT_VERSIONS.get(h, "p-" + h[:12])
    return _VERSIONS[k]


# The version for this project's pair, for the tools that report on one.
PROMPT_VERSION = prompt_version(os.environ.get("TR_SRC", "sl"), _env_target())

# A Slovene amount: optional period-grouped thousands, comma decimal, one or
# two decimal digits. The lookarounds keep it from starting or ending inside a
# longer run of digits and separators. A full stop after it ends the sentence,
# not the number, unless a digit follows: "12.450,00." is an amount, while
# "5.10.2024" is not one followed by more of it.
_SL_AMOUNT = re.compile(r"(?<![\d,.])(\d{1,3}(?:\.\d{3})*|\d+),(\d{1,2})(?![\d,]|\.\d)")
_EN_AMOUNT = re.compile(r"(?<![\d,.])(\d{1,3}(?:,\d{3})*|\d+)\.(\d{1,2})(?![\d,]|\.\d)")
# A whole number with its thousands grouped, 1.250 or 1,250.
_SL_GROUPED = re.compile(r"(?<![\d,.])\d{1,3}(?:\.\d{3})+(?!\d|[.,]\d)")
_EN_GROUPED = re.compile(r"(?<![\d,.])\d{1,3}(?:,\d{3})+(?!\d|[.,]\d)")
_COMMA_DECIMAL = {"sl", "de"}
_POINT_DECIMAL = {"en"}


def _regroup(digits, sep):
    out = []
    while len(digits) > 3:
        out.insert(0, digits[-3:])
        digits = digits[:-3]
    out.insert(0, digits)
    return sep.join(out)


# Words after which a number is a reference, not a quantity -- Section 5.10,
# Art. 3.2, clause 3.2, § 5.1 -- in English, and in the German or Slovene a
# draft may have put them into. A list after the word counts too, so the 3.3
# of "Articles 3.2 and 3.3" is a reference as well.
_REFERENCE_WORDS = (
    r"sections?|secs?|subsections?|articles?|arts?|paragraphs?|paras?|"
    r"clauses?|sub-?clauses?|schedules?|annex(?:es)?|appendix|appendices|"
    r"exhibits?|chapters?|chaps?|parts?|items?|points?|rules?|regulations?|"
    r"nos?|numbers?|versions?|"
    r"abschnitts?|abschnitte|artikels?|absatz|absätze|abs|ziffer|ziffern|"
    r"ziff|nummer|nr|kapitel|klauseln?|punkte?|anhang|anlage|teil|"
    r"randnummer|rn|rz|"
    r"člen|členi|člena|čl|odstavek|odstavka|odst|točka|točke|tč|poglavje|"
    r"oddelek|priloga|št")
_REFERENCE_BEFORE = re.compile(
    r"(?:\b(?:" + _REFERENCE_WORDS + r")\.?|§§?)\s*"
    r"(?:\d+(?:\.\d+)*[a-z]?\)?\s*(?:,|;|&|and|or|to|und|oder|bis|in|ali|do"
    r"|-|–)\s*)*$", re.I)
# A time written with a period: at 10.30, 10.30 a.m., um 14.30, 14.30 Uhr.
# Switzerland writes every time this way, so a Swiss draft's 14.30 Uhr is the
# conversion done, not an amount left undone.
_PERIOD_TIME = re.compile(r"(?:[01]?\d|2[0-3])\.[0-5]\d")
_TIME_BEFORE = re.compile(r"\b(?:at|until|till|um|ob)\s*$", re.I)
_TIME_AFTER = re.compile(
    r"\s*(?:[ap]\.?\s?m\b\.?|h\b|hrs?\b|hours\b|o'clock|uhr\b|uri\b|ura\b)", re.I)
_QUANTITY_AFTER = re.compile(r"\s*(?:%|per\s?cent|percent|prozent|odstot)", re.I)


def _protected(text, start, end):
    """Is the number at text[start:end] a reference or a time where it
    stands? A currency or a percent beside it makes it a quantity whatever
    word is before it."""
    before = text[max(0, start - 80):start]
    if _REFERENCE_BEFORE.search(before):
        return True
    if not _PERIOD_TIME.fullmatch(text[start:end]):
        return False
    if (_CURRENCY_BEFORE.search(before) or _CURRENCY_AFTER.match(text, end)
            or _QUANTITY_AFTER.match(text, end)):
        return False
    return bool(_TIME_BEFORE.search(before) or _TIME_AFTER.match(text, end))


def _rewrite_numbers(tgt, numbers, spell, guarded):
    """tgt with each of numbers respelled by spell(number, match) wherever it
    stands whole: not inside a longer run of digits and separators, so a
    source's 1.50 leaves a draft's 11.50 alone. With guarded, one that is a
    reference or a time where it stands in tgt is left as it is.

    One pass, longest first, so 1.234.567,89 is not partly rewritten by a
    shorter number inside it and nothing is respelled twice.
    """
    if not numbers:
        return tgt
    rx = re.compile(r"(?<![\d.,])(?:"
                    + "|".join(map(re.escape, sorted(numbers, key=len, reverse=True)))
                    + r")(?![\d,]|\.\d)")

    def swap(m):
        if guarded and _protected(tgt, m.start(), m.end()):
            return m.group(0)
        return spell(m.group(0), m) or m.group(0)
    return rx.sub(swap, tgt)


def _restore_references(tgt, numbers):
    """tgt with each of numbers -- a reference or a time everywhere the source
    has it -- put back where the draft writes it as a decimal: 5,10 for
    Section 5.10, 10,30 for 10.30 Uhr. The source has no such quantity, so the
    comma can only be a rewrite of the reference, made by the model or by
    this kit before it recognised references. Memory rows written then are
    finished again when read, and this is what repairs them."""
    commas = {n.replace(".", ","): n for n in numbers if _AMBIGUOUS_POINT.fullmatch(n)}
    return _rewrite_numbers(tgt, set(commas), lambda comma, _m: commas[comma], False)


def fix_numeric_format(src, tgt, src_lang, tgt_lang):
    """Rewrite amounts the model left in the source's number format.

    WHY THIS IS NOT LEFT TO THE MODEL

    The prompt tells it to convert 12.450,00 to 12,450.00 and it mostly does,
    but "mostly" is the wrong standard for a figure in a legal document, and
    the translator found whole tables of amounts still carrying the Slovene
    comma. Fixing those by hand is exactly the tedium this pipeline exists to
    remove. Separator conversion is arithmetic; it does not need a language
    model and should not depend on one.

    DRIVEN FROM THE SOURCE, NOT THE TARGET

    The obvious implementation -- find source-format numbers in the target and
    swap the separators -- is unsafe in the en->sl direction, where "5.10" is
    both an amount and a section reference and nothing in the string says
    which. So this only rewrites a number that literally appeared in the
    SOURCE in source format and survived into the target unchanged. It cannot
    invent a conversion, and a target number with no counterpart in the source
    is left alone.

    Idempotent: a number the model already converted no longer matches the
    source-format pattern, so it is not touched twice.

    GERMAN writes amounts exactly as Slovene does, 12.450,00, so what decides
    a conversion is which side writes a decimal comma, not which language
    it is. sl<->de therefore converts nothing.

    FROM ENGLISH, THE WORDS AROUND A NUMBER DECIDE. English writes both "1.50"
    as an amount and "5.10" as a section reference, and nothing in the string
    tells them apart. So a number after a reference word -- Section 5.10,
    Art. 3.2, clauses 3.2 and 3.3, § 5.1 -- or in a time -- at 10.30,
    10.30 a.m., 14.30 Uhr -- is left as it stands, whether the source or the
    draft says so; see _protected(). Anything else is converted, and tr-lint's
    DEC check lists every number of that shape written as a decimal, for the
    reviewer to confirm. The comma-to-point directions have no such
    ambiguity, because a Slovene or German amount needs a comma decimal and a
    section reference never has one.
    """
    if not src or not tgt:
        return tgt
    if src_lang in _POINT_DECIMAL and tgt_lang == "de-CH":
        return _fix_swiss_numbers(src, tgt)
    if src_lang in _COMMA_DECIMAL and tgt_lang in _POINT_DECIMAL:
        pat, grouped, thou_out, dec_out, strip, guarded = \
            _SL_AMOUNT, _SL_GROUPED, ",", ".", ".", False
    elif src_lang in _POINT_DECIMAL and tgt_lang in _COMMA_DECIMAL:
        pat, grouped, thou_out, dec_out, strip, guarded = \
            _EN_AMOUNT, _EN_GROUPED, ".", ",", ",", True
    else:
        return tgt

    subs, kept = {}, set()
    for m in pat.finditer(src):
        if guarded and _protected(src, m.start(), m.end()):
            kept.add(m.group(0))
            continue
        digits = m.group(1).replace(strip, "")
        subs[m.group(0)] = _regroup(digits, thou_out) + dec_out + m.group(2)
    # A whole number with its thousands grouped is converted too: to a German
    # reader, 1,250 shares are one and a quarter. A group of three digits is
    # no decimal in either notation, but after a reference word, in the
    # source or in the draft, it is left.
    whole = {m.group(0) for m in grouped.finditer(src)
             if not _protected(src, m.start(), m.end())}
    for number in whole:
        subs[number] = number.replace(strip, thou_out)

    def spell(number, m):
        if number in whole and _protected(tgt, m.start(), m.end()):
            return None
        return subs[number]
    # A number that is a reference or a time anywhere in the source is not
    # rewritten anywhere in the draft, which may have moved it.
    tgt = _rewrite_numbers(tgt, set(subs) - kept, spell, guarded)
    return _restore_references(tgt, kept - set(subs)) if guarded else tgt


_CURRENCY_BEFORE = re.compile(rf"(?:{_CURRENCY})\s*$")
_CURRENCY_AFTER = re.compile(rf"\s*(?:{_CURRENCY})")
# The other end of a range with the currency beside it: the 2,000.00 of
# "CHF 1,000.00 to 2,000.00", and the 1,000.00 of "1,000.00 to 2,000.00 CHF".
_RANGE_JOIN = r"(?:[–-]|to|and|or|bis|und|oder)"
_CURRENCY_RANGE_BEFORE = re.compile(
    rf"(?:{_CURRENCY})\s*\d[\d.,'’\u00a0 ]*?\s*{_RANGE_JOIN}\s*$")
_CURRENCY_RANGE_AFTER = re.compile(
    rf"\s*{_RANGE_JOIN}\s*\d[\d.,'’\u00a0 ]*?\s*(?:{_CURRENCY})")


def _money_where(text, start, end):
    """Is the number at text[start:end] money where it stands: a currency
    beside it, or beside the other end of its range, and no percent?"""
    if _QUANTITY_AFTER.match(text, end):
        return False
    before = text[max(0, start - 80):start]
    return bool(_CURRENCY_BEFORE.search(before) or _CURRENCY_AFTER.match(text, end)
                or _CURRENCY_RANGE_BEFORE.search(before)
                or _CURRENCY_RANGE_AFTER.match(text, end))


def _fix_swiss_numbers(src, tgt):
    """fix_numeric_format() for English into Swiss German.

    Driven from the source the same way, and guarded the same way. Each
    number the source has is rewritten where the draft writes it the English
    way, 12,450.00, or Germany's, 12.450,00: Switzerland writes neither.
    Whether it is money is read where it stands in the draft, from a currency
    beside it or beside the other end of its range: CHF 12,450.00 becomes
    CHF 12 450.00, the 2,000.00 of "CHF 1,000.00 to 2,000.00" is money too,
    and a bare 3.25 becomes 3,25. The currency stays where the model put it;
    the prompt asks for it first, and moving words within a sentence is not
    arithmetic.
    """
    found, kept, bare = set(), set(), set()
    for pat in (_EN_AMOUNT, _EN_GROUPED):
        for m in pat.finditer(src):
            if _protected(src, m.start(), m.end()):
                kept.add(m.group(0))
                continue
            found.add(m.group(0))
            if not _money_where(src, m.start(), m.end()):
                bare.add(m.group(0))
    # Each number by the spellings it may have in the draft: its own, and
    # Germany's where that is not a spelling the source has as well.
    english = {n: n for n in found}
    for n in found:
        german = _en_number_to_sl(n)
        if german and german not in found | kept:
            english.setdefault(german, n)

    def spell(number, m):
        n = english[number]
        # Money where the draft puts a currency beside it; where it puts
        # none, money if the source never wrote it bare. "Interest of 2.50
        # on CHF 2.50" has one of each.
        money = _money_where(tgt, m.start(), m.end()) or (
            n not in bare and not _QUANTITY_AFTER.match(tgt, m.end()))
        return _swiss_number(n, money)
    return _restore_references(_rewrite_numbers(tgt, set(english), spell, guarded=True),
                               kept - found)


_SPACED_GROUPS = re.compile(r"(?<![\d.,'’\u00a0])(\d{1,3})((?: \d{3})+)(?!\d)")


def _swiss_spacing(text):
    """Non-breaking spaces in a number of five digits or more whose groups the
    model separated with plain ones, so that no line break splits it. A
    spaced four-digit number is left alone: joining it would be right if it
    is one number and wrong if it is two."""
    def nbsp(m):
        if len(m.group(1)) + len(m.group(2).replace(" ", "")) < 5:
            return m.group(0)
        return m.group(1) + m.group(2).replace(" ", NBSP)
    return _SPACED_GROUPS.sub(nbsp, text)


# A time in English: 14:30, or 2:30 p.m. and 2:30pm with the marker after it.
_COLON_TIME = re.compile(r"(?<![\d:.,])(\d{1,2}):([0-5]\d)(?![\d:])")
_MARKER_AFTER = re.compile(r"\s*([ap])\.?\s?m\b\.?", re.I)
# A time in a German draft, where a spaced "am" is German: "um 12:00 am
# Montag" is on Monday. An English marker the model left in is written a.m.
# or p.m., joined as in 2:30pm, or spaced as pm or AM.
_DRAFT_TIME = re.compile(
    r"(?<![\d:.,])(\d{1,2}):([0-5]\d)(?![\d:])"
    r"(?P<marker>\s*[aApP]\.\s?[mM]\.|[aApP][mM]\b|\s+[pP][mM]\b|\s+AM\b)?")


def _clock(hour, minute, marker=None):
    """(hour, minute) on the 24-hour clock, or None if it is no time."""
    h = int(hour)
    if marker:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if marker in "pP" else 0)
    return (h, minute) if h <= 23 else None


def _swiss_times(src, tgt):
    """The draft's times written 14:30 or 2:30 p.m., written as Switzerland
    writes them: 14.30. Only a time the source has, by value, so a ratio in
    the draft is left."""
    times = set()
    for m in _COLON_TIME.finditer(src):
        after = _MARKER_AFTER.match(src, m.end())
        times.add(_clock(m.group(1), m.group(2), after and after.group(1)))
    times.discard(None)

    def swap(m):
        marker = m.group("marker")
        twelve = marker and _clock(m.group(1), m.group(2), marker.strip()[0])
        if twelve in times:
            return f"{twelve[0]}.{twelve[1]}"
        plain = _clock(m.group(1), m.group(2))
        if plain in times:
            return f"{plain[0]}.{plain[1]}{marker or ''}"
        return m.group(0)
    return _DRAFT_TIME.sub(swap, tgt) if times else tgt


# A whole number of francs, however the draft writes it -- CHF 20.00,
# 20.00 CHF, Fr. 20.-, Fr. 20.— -- is written Fr. 20.–, as localize() writes
# it, so that both write one form. Not before a word of scale: CHF 20.00 Mio.
# is left as it stands.
_FRANCS = r"\d{1,3}(?:[ \u00a0]\d{3})+|\d+"
_WHOLE_FRANCS = re.compile(
    r"\b(?:CHF\b|Fr\.)[ \u00a0]?(?P<a>" + _FRANCS + r")\.(?:00|\u2060?[–—-])(?!\d)"
    r"(?![ \u00a0]*(?:Mio|Mrd|Mill|Tsd|Tausend))"
    r"|(?<![\d.,'’])(?P<b>" + _FRANCS + r")\.(?:00|\u2060?[–—-])[ \u00a0]?(?:CHF\b|Fr\.)")


def _whole_francs(text):
    """Whole franc amounts as Fr. 20.–, held on one line: a no-break space
    after Fr., and a word joiner before the dash. Without them LibreOffice set
    "Fr. 20." at the end of a line and the dash at the start of the next; with
    the joiner alone it left Fr. behind instead."""
    return _WHOLE_FRANCS.sub(
        lambda m: f"Fr.{NBSP}{m.group('a') or m.group('b')}.{WJ}–", text)


def finish_draft(src, tgt, src_lang, tgt_lang):
    """A model reply made ready to store: its number format fixed and, in
    Swiss German, its times written 14.30, its digit groups and whole franc
    amounts written the Swiss way and held together, and ß written ss. Every
    draft passes through here before it enters the memory, so the memory
    holds what the deliverable shows."""
    tgt = fix_numeric_format(src, tgt, src_lang, tgt_lang)
    if tgt and tgt_lang == "de-CH":
        tgt = swiss_spelling(src, _whole_francs(_swiss_spacing(_swiss_times(src, tgt))))
    return tgt


def refinish(src, cached, src_lang, tgt_lang, gloss_sig):
    """A memory row, finished as a draft made today would be.

    The memory's key covers the model, the prompt and the glossary, not how a
    reply is finished, so a row written before a finishing fix came back
    without it: a sentence-final 12.450,00 left in an English draft, a Swiss
    Fr. 20.– that could break across a line, a Section 5,10. Every row read is
    finished again, and stored back when that changes it, so the memory keeps
    holding what the deliverables show. finish_draft() changes nothing in a
    row that is already finished.
    """
    done = finish_draft(src, cached, src_lang, tgt_lang)
    if done != cached:
        tm_put(src, done, f"{src_lang}-{tgt_lang}", gloss_sig)
    return done


def decimal_rewrites(src, tgt, src_lang, tgt_lang):
    """Numbers in an English source that read as well as a reference or a
    time -- 5.10, 3.2, 14.30, with no currency or percent beside them -- and
    stand in the draft as decimals, 5,10. Whoever converted one, the model or
    fix_numeric_format(), nothing in the string says whether that was right,
    so tr-lint lists them for the reviewer."""
    if src_lang not in _POINT_DECIMAL or base_lang(tgt_lang) not in _COMMA_DECIMAL:
        return []
    out = []
    for m in _EN_AMOUNT.finditer(src or ""):
        number = m.group(0)
        if (number in out or not _AMBIGUOUS_POINT.fullmatch(number)
                or _CURRENCY_BEFORE.search(src, 0, m.start())
                or _CURRENCY_AFTER.match(src, m.end())
                or _QUANTITY_AFTER.match(src, m.end())):
            continue
        comma = re.escape(number.replace(".", ","))
        if re.search(r"(?<![\d.,])" + comma + r"(?![\d,]|\.\d)", tgt or ""):
            out.append(number)
    return out


# ------------------------------------------------ replies that are not translations

# Asked to translate the bare heading STATEMENT, EuroLLM returned an invented
# German declaration: a claimant, a vehicle, numbered clauses, blanks for a
# date and a signature. It reads as a plausible document, and tr-lint noticed
# only because the invention happened to contain numbers. A label or heading
# is exactly where a model has least to go on and most room to write.
#
# A translation is not three times the length of its source, and a one-line
# source does not translate into several lines. Both limits are generous on
# purpose: this is a test for text that was added, not for wordy German.
FIRM_PREFIX = ("Translate only the text below. Reply with its translation "
               "and nothing else.\n\n")


def implausible(src, tgt):
    """Is this reply far longer than any translation of the source could be?"""
    s, t = (src or "").strip(), (tgt or "").strip()
    if "\n" in t and "\n" not in s:
        return True
    return len(t) > 3 * len(s) + 40


def added_numbers(src, tgt, src_lang=None, tgt_lang=None):
    """Numbers in the reply that the source does not have, dates and
    separators folded first. The same comparison as tr-lint's NUM check.

    Length does not catch every invention. "Case number" came back once as
    "Klage Nr. 2 BvR 237/09" -- a fictitious court reference, short enough to
    pass as a translation of a label. What gives it away is a number with no
    counterpart in the source, and an invented identifier in a legal
    document is the most expensive thing this pipeline can produce.

    Such a reply earns one firmer retry, not a refusal: a model that writes
    "dva tedna" as "2 weeks" has added a digit without adding anything false,
    and turning that into a failed segment would cost the translator more
    than tr-lint's NUM finding does.
    """
    return compare_numbers(src, tgt, src_lang, tgt_lang)[1]


def number_distance(src, tgt, src_lang=None, tgt_lang=None):
    """How far a reply's numbers are from its source's, as values: the
    numbers it adds plus the numbers it drops."""
    lost, added = compare_numbers(src, tgt, src_lang, tgt_lang)
    return sum(lost.values()) + sum(added.values())


def max_tokens(text):
    """A generation cap no genuine translation reaches -- a token is rarely
    shorter than a character -- which bounds what an invention costs. At
    three tokens a second an unbounded one ran for minutes."""
    return len(text) + 64


# ------------------------------------------------ reference translations

_REFERENCES = None
REF_HITS = 0
REF_OPTION_HITS = 0
# Everything reference_translation() returned, so that a worker can tell the
# translator's own words from a draft: FirstMention writes them as they are.
REFERENCE_TEXTS = set()
# Segments the model could not translate, written [TRANSLATION FAILED]. A
# worker that wrote any exits non-zero, so tr-run counts its file as failed,
# records nothing for it, and drafts it again on the next run.
FAILED = 0


def reference_translation(text, direction, gloss=None):
    """The translator's own rendering of this exact sentence, a REF_OPTIONS
    token offering the renderings to choose from, or None when no reference
    has the sentence.

    From the project's reference/ folder, lined up by tr-ref; lib/trref.py
    says what is kept, how renderings are ordered, and when the draft carries
    options. Checked before the memory and before the model: a sentence a
    certifying translator has already translated is not a draft, and where
    their renderings disagree the choice is theirs. The glossary only orders
    the options.
    """
    global _REFERENCES, REF_HITS, REF_OPTION_HITS
    import trref
    if _REFERENCES is None:
        _REFERENCES = {}
        if ROOT and os.path.isdir(ROOT):
            _REFERENCES = trref.load_references()
    s, t = split_direction(direction)
    rows = _REFERENCES.get(f"{s}-{base_lang(t)}", {}).get(
        " ".join((text or "").split()))
    if not rows:
        return None
    found = trref.resolve(rows, direction, text, gloss)[0]
    if found.startswith(trref.OPTIONS_MARK):
        REF_OPTION_HITS += 1
    else:
        REF_HITS += 1
    REFERENCE_TEXTS.add(found)
    return found


def ollama_translate(text, src_lang, tgt_lang, gloss=None, retries=3, first=None):
    # Every draft and every memory row passes through here or through
    # ollama_translate_many(), so the pair is settled here as well as in the
    # workers, for any caller that did not. Written de-DE, a target selects
    # none of the German rules from the prompt and keys its rows under a
    # direction no Germany run reads.
    #
    # first is a reply the text already has, from a batch that flagged it. It
    # is judged as the first reply, so that only a retry costs a call.
    src_lang, tgt_lang = translation_pair(src_lang, tgt_lang)
    local = _local_value(text, src_lang, tgt_lang)
    if local is not None:
        return local          # a date, a time or an amount: converted in code
    if not is_translatable(text):
        return text
    ref = reference_translation(text, f"{src_lang}-{tgt_lang}", gloss)
    if ref is not None:
        return ref
    gb = glossary_block(text, gloss or [])
    cached = tm_get(text, f"{src_lang}-{tgt_lang}", gb)
    if cached is not None:
        return refinish(text, cached, src_lang, tgt_lang, gb)
    system = build_prompt(src_lang, tgt_lang, gb)
    last, firm, fallback, tries = None, False, None, 0
    for attempt in range(retries):
        tries = attempt + 1
        payload = {
            "model": require_model(src_lang, tgt_lang),
            "system": system,
            # After an implausible reply the identical request would most
            # likely get the identical reply, so the retry says plainly that
            # this text, and only this text, is to be translated.
            "prompt": (FIRM_PREFIX + text) if firm else text,
            "stream": False,
            "options": {"temperature": 0.1, "top_p": 0.9, "num_ctx": NUM_CTX,
                        "num_predict": max_tokens(text)},
        }
        req = urllib.request.Request(
            OLLAMA + "/api/generate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            cut = False
            if attempt == 0 and first is not None:
                out = first
            else:
                with urllib.request.urlopen(req, timeout=1800) as r:
                    reply = json.loads(r.read())
                out = reply["response"].strip()
                # Stopped by num_predict rather than finished: the end of the
                # translation is missing, however well the start reads.
                cut = reply.get("done_reason") == "length"
            out = re.sub(r"^```.*?\n|```$", "", out, flags=re.S).strip()
            if out and (cut or implausible(text, out)):
                last = ("the reply was cut off at the length limit" if cut
                        else "the reply was far longer than the source")
                if firm:
                    break
                firm = True
                continue
            if out and not firm and added_numbers(text, out, src_lang, tgt_lang):
                fallback, firm = out, True
                continue
            if out:
                # Of the first reply and the firmer one, the one whose numbers
                # are nearer the source's as values: a number dropped counts
                # as much as one added. Counting added numbers alone let a
                # firm reply win by dropping a date. On a tie the firmer reply
                # stands. tr-lint reports whatever is left as NUM.
                if (fallback is not None
                        and number_distance(text, out, src_lang, tgt_lang)
                        > number_distance(text, fallback, src_lang, tgt_lang)):
                    out = fallback
                out = finish_draft(text, out, src_lang, tgt_lang)
                tm_put(text, out, f"{src_lang}-{tgt_lang}", gb)
                return out
            last = "empty response"
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))
    if fallback is not None:
        out = finish_draft(text, fallback, src_lang, tgt_lang)
        tm_put(text, out, f"{src_lang}-{tgt_lang}", gb)
        return out
    global FAILED
    FAILED += 1
    print(f"  ! translation failed after {tries} {'try' if tries == 1 else 'tries'}: "
          f"{last}", file=sys.stderr)
    return f"[TRANSLATION FAILED] {text}"

# Batching thresholds. Deliberately conservative: a batch that comes back
# misaligned is worse than a slow run, so only short single-line segments are
# grouped, and any doubt falls back to one call per segment.
BATCH_MAX_ITEMS = int(os.environ.get("TR_BATCH_ITEMS", "20"))
BATCH_MAX_CHARS = int(os.environ.get("TR_BATCH_CHARS", "1500"))
BATCH_ITEM_CHARS = int(os.environ.get("TR_BATCH_ITEM_CHARS", "200"))

_NUMBERED = re.compile(r"^\s*(\d+)\s*[.)]\s?(.*)$")


def _batchable(t):
    """Short, single-line, and free of the numbering we use as the frame."""
    return ("\n" not in t and len(t) <= BATCH_ITEM_CHARS
            and not _NUMBERED.match(t))


def _translate_batch(texts, src_lang, tgt_lang, gloss):
    """One request for several segments. Returns [(reply, flagged)], one per
    segment, or None if the reply did not line up exactly with the input.

    Returning None rather than a best guess is the whole safety property:
    a silently misaligned batch would attach every translation to the wrong
    cell, and nothing downstream could detect it -- each segment would look
    like a perfectly good translation of some other segment.
    """
    gb = glossary_block("\n".join(texts), gloss or [])
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1))
    payload = {
        "model": require_model(src_lang, tgt_lang),
        # Same system prompt as the single-segment path, so both share one
        # cache namespace and one set of rules. The batch framing goes in the
        # user turn.
        "system": build_prompt(src_lang, tgt_lang, gb),
        "prompt": ("Translate each numbered line separately. Reply with the "
                   "same numbers in the same order, one translation per line, "
                   "and nothing else.\n\n" + numbered),
        "stream": False,
        "options": {"temperature": 0.1, "top_p": 0.9, "num_ctx": NUM_CTX,
                    "num_predict": max_tokens(numbered) + 16 * len(texts)},
    }
    req = urllib.request.Request(
        OLLAMA + "/api/generate", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            reply = json.loads(r.read())
        out = reply["response"].strip()
    except Exception:
        return None
    if reply.get("done_reason") == "length":
        return None                        # cut off: its last lines are missing
    out = re.sub(r"^```.*?\n|```$", "", out, flags=re.S).strip()

    got = {}
    for ln in out.splitlines():
        m = _NUMBERED.match(ln)
        if m:
            idx = int(m.group(1))
            if idx in got:                 # repeated number: cannot trust it
                return None
            got[idx] = m.group(2).strip()
    if set(got) != set(range(1, len(texts) + 1)):
        return None
    if any(not v for v in got.values()):
        return None
    # A line that invented something is flagged, and goes through the
    # single-segment path, which retries it -- and refuses it outright if it
    # is far longer than its source. Only that line: sending the whole batch
    # after it turned one correctly converted date into twenty separate calls.
    return [(got[i], implausible(t, got[i])
             or bool(added_numbers(t, got[i], src_lang, tgt_lang)))
            for i, t in enumerate(texts, 1)]


def ollama_translate_many(texts, src_lang, tgt_lang, gloss=None, report=None):
    """Translate a list of segments, grouping the short ones.

    WHY

    Measured on a real run: 370 spreadsheet cells took 22,075 seconds, 59.7
    each, for strings like a name and a month. That is not generation -- it
    is a fixed per-call cost of about a minute, paid in full by an eight
    token cell, because every call re-prefills the system prompt on a
    memory-bandwidth-bound 12B model. One spreadsheet was 67% of a nine hour
    run.

    Grouping twenty short segments into one request pays that cost once
    instead of twenty times. Long or multi-line segments are left alone:
    they have real generation cost to amortise against, and they are the
    ones most likely to confuse the numbering.

    Every result is still cached individually, so a bumped prompt version or
    an interrupted run loses nothing extra, and tr-lint sees exactly what it
    saw before.
    """
    src_lang, tgt_lang = translation_pair(src_lang, tgt_lang)   # see ollama_translate()
    direction = f"{src_lang}-{tgt_lang}"
    out = [None] * len(texts)
    pending = []

    for i, t in enumerate(texts):
        local = _local_value(t, src_lang, tgt_lang)
        if local is not None or not is_translatable(t):
            out[i] = t if local is None else local
            continue
        ref = reference_translation(t, direction, gloss)
        if ref is not None:
            out[i] = ref
            continue
        gb = glossary_block(t, gloss or [])
        cached = tm_get(t, direction, gb)
        if cached is not None:
            out[i] = refinish(t, cached, src_lang, tgt_lang, gb)
            continue
        pending.append(i)

    done = len(texts) - len(pending)
    batch = []

    def flush():
        nonlocal batch, done
        if not batch:
            return
        idxs = batch
        batch = []
        got = _translate_batch([texts[i] for i in idxs], src_lang, tgt_lang, gloss)
        if got is None:
            # Misaligned or failed: redo this group one at a time. Slower for
            # this group only, and correct.
            for i in idxs:
                out[i] = ollama_translate(texts[i], src_lang, tgt_lang, gloss)
                done += 1
                if report:
                    report(done, len(texts), texts[i])
            return
        for i, (tr, flagged) in zip(idxs, got):
            if flagged:
                out[i] = ollama_translate(texts[i], src_lang, tgt_lang, gloss, first=tr)
            else:
                tr = finish_draft(texts[i], tr, src_lang, tgt_lang)
                out[i] = tr
                # Keyed on the terms that apply to THIS segment, matching the
                # single-segment path -- not on the block the batch was sent
                # with, which is the union across twenty segments.
                tm_put(texts[i], tr, direction, glossary_block(texts[i], gloss or []))
            done += 1
            if report:
                report(done, len(texts), texts[i])

    chars = 0
    for i in pending:
        t = texts[i]
        if not _batchable(t):
            flush()
            out[i] = ollama_translate(t, src_lang, tgt_lang, gloss)
            done += 1
            if report:
                report(done, len(texts), t)
            continue
        if batch and (len(batch) >= BATCH_MAX_ITEMS
                      or chars + len(t) > BATCH_MAX_CHARS):
            flush()
            chars = 0
        batch.append(i)
        chars += len(t)
    flush()
    return out


def progress(i, n, label=""):
    pct = 100.0 * i / n if n else 100.0
    sys.stderr.write(f"\r  {i}/{n} ({pct:.0f}%) {label[:50]:<50}")
    sys.stderr.flush()
    if i == n:
        sys.stderr.write("\n")
