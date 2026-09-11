"""Temporary files stay inside the project: what OCR writes while it works
never reaches TMPDIR. Audit 2026-09-10: H-8."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import os
import shutil
import subprocess
import tempfile
import time
import unittest


def image_pdf(path, lines):
    """A PDF holding only a picture of the text, as a scanner makes one.
    Built with the system python3's img2pdf, which the kit venv lacks."""
    text = path + ".text.pdf"
    support.write_pdf(text, lines)
    subprocess.run(["pdftoppm", "-png", "-r", "150", "-singlefile", text, path + ".page"],
                   check=True)
    subprocess.run(["python3", "-c", "import sys, img2pdf; open(sys.argv[2], 'wb')"
                    ".write(img2pdf.convert(sys.argv[1]))", path + ".page.png", path],
                   check=True)
    os.remove(text)
    os.remove(path + ".page.png")


class TempFiles(unittest.TestCase):

    def test_ocr_writes_nothing_to_tmpdir(self):
        tools = ("ocrmypdf", "tesseract", "pdftoppm", "python3")
        if not all(shutil.which(t) for t in tools) or subprocess.run(
                ["python3", "-c", "import img2pdf"], capture_output=True).returncode:
            self.skipTest("needs ocrmypdf, tesseract, pdftoppm and python3's img2pdf")
        root = support.project("tmpdir", "sl", "en")
        pdf = f"{root}/source/scan.pdf"
        image_pdf(pdf, support.SLOVENE_LINES)
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
