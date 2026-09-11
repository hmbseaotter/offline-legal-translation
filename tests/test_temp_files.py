"""Temporary files stay inside the project: what OCR writes while it works
never reaches TMPDIR. Audit 2026-09-10: H-8."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import os
import subprocess
import tempfile
import time
import unittest


class TempFiles(unittest.TestCase):

    def test_ocr_writes_nothing_to_tmpdir(self):
        if not support.can_scan():
            self.skipTest("needs ocrmypdf, tesseract, pdftoppm and python3's img2pdf")
        root = support.project("tmpdir", "sl", "en")
        pdf = f"{root}/source/scan.pdf"
        support.image_pdf(pdf, support.SLOVENE_LINES)
        watched = tempfile.mkdtemp(prefix="watched-", dir=support.ROOT)
        env = dict(os.environ, TR_ROOT=root, TMPDIR=watched, TR_OCR_LANGS="eng")
        run = subprocess.Popen([os.path.join(support.BIN, "tr-pdf"), "--ocr-only", pdf],
                               env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
        seen = set()
        while run.poll() is None:
            for dp, dirs, files in os.walk(watched):
                seen.update(os.path.relpath(os.path.join(dp, n), watched)
                            for n in dirs + files)
            time.sleep(0.05)
        out = run.stdout.read()
        self.assertEqual(run.returncode, 0, out)
        self.assertIn("OCR (eng)", out)
        self.assertEqual(seen, set(), out)
        self.assertTrue(os.path.exists(f"{root}/work/ocr/scan.txt"), out)
        self.assertEqual(os.listdir(f"{root}/work/tmp"), [])


if __name__ == "__main__":
    unittest.main()
