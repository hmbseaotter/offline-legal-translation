"""A segment the model cannot translate: the worker fails, tr-run records
nothing and exits non-zero, tr-lint lists it, and the next run drafts the file
again. Audit 2026-09-10: M-4, L-1."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import os
import unittest

INVENTED = ("ERKLÄRUNG\n1. Ich erkläre hiermit, dass alle Angaben wahr sind.\n"
            "2. Unterschrift: ________")


class Failures(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mock = support.Mock()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def test_a_failed_segment_fails_its_file(self):
        root = support.project("failed", "en", "de")
        src, out = f"{root}/source/labels.docx", f"{root}/translated/labels.docx"
        support.write_docx(src, ["DECLARATION", "Date"])

        self.mock.set({"map": {"DECLARATION": INVENTED},
                       "map_firm": {"DECLARATION": INVENTED}})
        code, log = support.run("tr-run", root, src, mock=self.mock)
        self.assertEqual(code, 1, log)
        self.assertIn("failed: 1", log)
        self.assertIn("after 2 tries", log)
        self.assertIn("[TRANSLATION FAILED] DECLARATION", support.read_docx(out))
        tsv = f"{root}/work/deliverables.tsv"
        if os.path.exists(tsv):
            with open(tsv, encoding="utf-8") as fh:
                self.assertNotIn("labels.docx", fh.read())
        _code, lint = support.run("tr-lint", root)
        self.assertIn("[FAIL] in labels.docx", lint)

        code, log = support.run("tr-run", root, src, mock=self.mock)
        self.assertEqual(code, 1, log)
        self.assertIn("redo   [1/1] labels.docx", log)

        self.mock.set({"map": {"DECLARATION": INVENTED},
                       "map_firm": {"DECLARATION": "ERKLÄRUNG"}})
        code, log = support.run("tr-run", root, src, mock=self.mock)
        self.assertEqual(code, 0, log)
        self.assertEqual(support.read_docx(out), ["ERKLÄRUNG", "<<Date>>"])
        _code, lint = support.run("tr-lint", root)
        self.assertNotIn("[FAIL]", lint)


if __name__ == "__main__":
    unittest.main()
