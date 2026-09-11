"""OCR text layers: one made without confidence marking is read again under
--with-ocr, and tr-ocrstat names the files it cannot measure. Audit
2026-09-10: H-1, and tr-ocrstat's exit status from M-13."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import os
import unittest

LINES = support.SLOVENE_LINES


class OcrLayers(unittest.TestCase):

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
        with open(layer, encoding="utf-8") as fh:
            self.assertNotIn("\f", fh.read())
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


if __name__ == "__main__":
    unittest.main()
