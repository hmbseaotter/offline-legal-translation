"""OCR text layers: one made without confidence marking is read again under
--with-ocr, but never in a loop and never over a copy set aside before; the
layer's name does not depend on how a path is spelled; tr-ocrstat names what
it cannot measure; a language recorded as unknown gives way once a scan is
read; and the OCR path asks nothing of Ghostscript, which AppArmor forbids
to write under $HOME, where the container is. Audit 2026-09-10: H-1, M-12,
M-13, M-14; 2026-09-25: every scan in the container failed at the PDF/A pass."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import csv
import os
import shutil
import subprocess
import tempfile
import unittest

LINES = support.SLOVENE_LINES


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def path_without(*tools):
    """A PATH on which the named tools cannot be found: a directory of links
    to everything else in the usual bin directories."""
    d = tempfile.mkdtemp(prefix="bin-", dir=support.ROOT)
    for src in ("/usr/local/bin", "/usr/bin", "/bin"):
        if os.path.isdir(src):
            for name in os.listdir(src):
                if name not in tools and not os.path.lexists(os.path.join(d, name)):
                    os.symlink(os.path.join(src, name), os.path.join(d, name))
    return d


def manifest(root):
    with open(f"{root}/work/inventory/manifest.tsv", encoding="utf-8") as fh:
        return {row["path"]: row for row in csv.DictReader(fh, delimiter="\t")}


class OcrLayers(unittest.TestCase):

    def tr_pdf(self, root, pdf, path=None, cwd=None, tr_root=None):
        env = dict(os.environ, TR_ROOT=tr_root or root)
        if path:
            env["PATH"] = path
        r = subprocess.run([os.path.join(support.BIN, "tr-pdf"), "--ocr-only", pdf],
                           env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=900)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout + r.stderr

    def test_with_ocr_reads_an_unmarked_layer_again(self):
        import trlang
        if not trlang.detector().ready():
            self.skipTest("language detection is not set up (tr-setup)")
        root = support.project("unmarked-layer", "sl", "en")
        support.write_pdf(f"{root}/source/scan.pdf", LINES)
        code, out = support.run("tr-inventory", root, "--count")
        self.assertEqual(code, 0, out)
        layer = f"{root}/work/ocr/scan.txt"
        # As the first --with-ocr wrote it: plain pdftotext, a form feed a page.
        support.write_text(layer, "\n".join(LINES) + "\n\f")
        code, out = support.run("tr-inventory", root, "--count", "--with-ocr")
        self.assertEqual(code, 0, out)
        self.assertNotIn("\f", read(layer))
        self.assertTrue(os.path.exists(layer + ".unmarked"))

    def test_tr_ocrstat_names_what_it_cannot_measure(self):
        root = support.project("ocrstat", "sl", "en")
        support.write_pdf(f"{root}/source/a/one.pdf", LINES)
        support.write_pdf(f"{root}/source/b/two.pdf", LINES)
        support.write_text(f"{root}/work/ocr/a__one.txt", "\n".join(LINES) + "\n\f")
        code, out = support.run("tr-ocrstat", root)
        self.assertEqual(code, 1, out)
        self.assertIn("a/one.pdf", out)
        self.assertIn("b/two.pdf", out)

    def test_a_layer_that_cannot_be_marked_is_not_read_again_in_a_loop(self):
        if not (shutil.which("tesseract") and shutil.which("pdftoppm")):
            self.skipTest("needs tesseract and pdftoppm")
        root = support.project("fallback", "sl", "en")
        pdf, layer = f"{root}/source/scan.pdf", f"{root}/work/ocr/scan.txt"
        # Too few words to be taken as born-digital, with its OCR already done,
        # so tr-pdf goes straight to tr-ocrtext.
        support.write_pdf(pdf, ["Kratka izjava prodajalca."])
        shutil.copy(pdf, f"{root}/work/ocr/scan.ocr.pdf")
        bare = path_without("tesseract", "pdftoppm")

        self.tr_pdf(root, pdf, path=bare)
        self.assertTrue(os.path.exists(layer + ".nomarks"))
        with open(layer, "a", encoding="utf-8") as fh:
            fh.write("POPRAVEK\n")                       # corrected by hand
        out = self.tr_pdf(root, pdf, path=bare)
        self.assertIn("cannot be read", out)
        self.assertIn("POPRAVEK", read(layer))
        self.assertFalse(os.path.exists(layer + ".unmarked"))

        self.tr_pdf(root, pdf)                           # tesseract available again
        self.assertIn("POPRAVEK", read(layer + ".unmarked"))
        self.assertFalse(os.path.exists(layer + ".nomarks"))

        support.write_text(layer, "plain pdftotext\n\f")  # another unmarked layer
        self.tr_pdf(root, pdf)
        self.assertIn("POPRAVEK", read(layer + ".unmarked"))
        self.assertTrue(any(f.startswith("scan.txt.unmarked-")
                            for f in os.listdir(f"{root}/work/ocr")))

    def test_the_layer_name_does_not_depend_on_how_paths_are_spelled(self):
        root = support.project("spelling", "sl", "en")
        support.write_pdf(f"{root}/source/a/born.pdf", LINES)
        self.tr_pdf(root, "source/a/born.pdf", cwd=root, tr_root=root + "/")
        self.assertEqual(sorted(os.listdir(f"{root}/work/ocr")),
                         ["a__born.sha256", "a__born.txt"])

    def test_with_ocr_replaces_a_language_recorded_as_unknown(self):
        import trlang
        if not (support.can_scan() and trlang.detector().ready()):
            self.skipTest("needs OCR tools, python3's img2pdf and language detection")
        root = support.project("unknown-language", "sl", "en")
        support.image_pdf(f"{root}/source/scan.pdf", LINES)
        code, out = support.run("tr-inventory", root, "--count")
        self.assertEqual(code, 0, out)
        self.assertEqual(manifest(root)["scan.pdf"]["lang"], "unknown")
        code, out = support.run("tr-inventory", root, "--count", "--with-ocr")
        self.assertEqual(code, 0, out)
        self.assertEqual(manifest(root)["scan.pdf"]["lang"], "sl", out)

    def test_no_pdfa_conversion_is_asked_of_ghostscript(self):
        """AppArmor's "gs" profile permits Ghostscript, under $HOME, only
        files whose extension it knows. Rasterizing is fine -- those are
        .png -- but the PDF/A pass needs a scratch file named gs_XXXXXX,
        which has no extension, so inside the container it fails after every
        page has been read. The shim records what Ghostscript is asked to do
        and then does it."""
        if not (support.can_scan() and shutil.which("gs")):
            self.skipTest("needs ocrmypdf, tesseract, pdftoppm, img2pdf and gs")
        root = support.project("gs-calls", "sl", "en")
        support.image_pdf(f"{root}/source/scan.pdf", LINES)
        shim = tempfile.mkdtemp(prefix="gs-shim-", dir=support.ROOT)
        asked = os.path.join(shim, "asked")
        support.write_text(os.path.join(shim, "gs"), f"""#!/bin/sh
printf '%s\\n' "$*" >> {asked}
exec {shutil.which("gs")} "$@"
""")
        os.chmod(os.path.join(shim, "gs"), 0o755)
        out = self.tr_pdf(root, f"{root}/source/scan.pdf",
                          path=shim + os.pathsep + os.environ["PATH"])
        self.assertGreater(len(read(f"{root}/work/ocr/scan.txt").split()), 20, out)
        calls = [c.split() for c in read(asked).splitlines()]
        pdfa = [" ".join(c) for c in calls if any(
            t.startswith("-dPDFA") or t.endswith("PDFA_def.ps") for t in c)]
        self.assertEqual(pdfa, [], "the PDF/A pass is back")
        # What the profile actually allows under $HOME is a file whose
        # extension it knows. Rasterizing writes .png and .jpg; the scratch
        # file of a PDF/A conversion has no extension at all.
        wrote = [c[c.index("-o") + 1] for c in calls if "-o" in c]
        self.assertTrue(wrote and all(os.path.splitext(w)[1] for w in wrote), wrote)

    def test_a_failed_ocr_records_why_it_failed(self):
        """"tr-pdf exit 7" alone sent an operator back to run tr-pdf by hand:
        an AppArmor denial, a missing ocrmypdf and a damaged PDF all read the
        same from the manifest."""
        if not support.can_scan():
            self.skipTest("needs ocrmypdf, tesseract, pdftoppm and img2pdf")
        root = support.project("ocr-why", "sl", "en")
        support.image_pdf(f"{root}/source/scan.pdf", LINES)
        env = dict(os.environ, TR_ROOT=root, PATH=path_without("ocrmypdf"))
        subprocess.run([os.path.join(support.BIN, "tr-inventory"), "--count",
                        "--with-ocr"], env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=900)
        method = manifest(root)["scan.pdf"]["method"]
        self.assertIn("pdf-ocr-failed", method)
        self.assertIn("ocrmypdf", method, method)
        self.assertNotIn("\t", method)


if __name__ == "__main__":
    unittest.main()
