"""project.conf reaches the shell tools, not only the Python ones.

tr-pdf took its OCR languages from the environment alone, so a hand-run in a
project whose project.conf named others told ocrmypdf one set of languages --
and said so in its banner -- while tr-ocrtext, which reads the file through
trlib, wrote the text layer in another. 2026-09-25."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import os
import subprocess
import unittest


class ProjectConf(unittest.TestCase):

    def ocr_banner(self, root, **env):
        """The line tr-pdf prints before it starts OCR'ing, which names the
        languages it will use. ocrmypdf is taken off PATH: the banner comes
        first, so this costs no OCR pass."""
        pdf = f"{root}/source/scan.pdf"
        support.image_pdf(pdf, support.SLOVENE_LINES)
        r = subprocess.run(
            [os.path.join(support.BIN, "tr-pdf"), "--ocr-only", pdf],
            env=dict(os.environ, TR_ROOT=root,
                     PATH=support.path_without("ocrmypdf"), **env),
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
        out = r.stdout + r.stderr
        said = [ln.strip() for ln in out.splitlines() if "OCR (" in ln]
        self.assertTrue(said, out)
        return said[0]

    def test_tr_pdf_ocrs_in_the_languages_the_project_names(self):
        if not support.can_scan():
            self.skipTest("needs ocrmypdf, tesseract, pdftoppm and img2pdf")
        root = support.project("conf-langs", "en", "sl")
        with open(f"{root}/project.conf", "a", encoding="utf-8") as fh:
            fh.write("TR_OCR_LANGS=eng+slv   # an English drop\n")
        self.assertEqual(self.ocr_banner(root), "OCR (eng+slv): scan.pdf")

    def test_an_explicit_setting_still_beats_the_file(self):
        """The file is the project's default, not an override of the operator:
        TR_OCR_LANGS=deu tr-pdf ... is a deliberate one-off and wins."""
        if not support.can_scan():
            self.skipTest("needs ocrmypdf, tesseract, pdftoppm and img2pdf")
        root = support.project("conf-override", "en", "sl")
        with open(f"{root}/project.conf", "a", encoding="utf-8") as fh:
            fh.write("TR_OCR_LANGS=eng+slv\n")
        self.assertEqual(self.ocr_banner(root, TR_OCR_LANGS="deu"),
                         "OCR (deu): scan.pdf")


if __name__ == "__main__":
    unittest.main()
