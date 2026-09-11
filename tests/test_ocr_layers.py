"""OCR text layers: one made without confidence marking is read again under
--with-ocr, but never in a loop and never over a copy set aside before; the
layer's name does not depend on how a path is spelled; tr-ocrstat names what
it cannot measure; and a language recorded as unknown gives way once a scan
is read. Audit 2026-09-10: H-1, M-12, M-13, M-14."""
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


if __name__ == "__main__":
    unittest.main()
