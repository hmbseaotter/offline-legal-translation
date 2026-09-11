"""Language pairs: a German source is refused until language detection knows
German and German->English has rules of its own. Audit 2026-09-10: H-9, M-15."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import unittest

import trlib


class Pairs(unittest.TestCase):

    def test_a_german_source_is_refused(self):
        with self.assertRaises(SystemExit) as refused:
            trlib.project_pair("de", "en")
        self.assertIn("German source is not supported", str(refused.exception.code))
        with self.assertRaises(SystemExit):
            trlib.project_pair("fr", "en")

    def test_the_supported_pairs(self):
        self.assertEqual(trlib.project_pair("sl", "en"), ("sl", "en"))
        self.assertEqual(trlib.project_pair("en", "de-DE"), ("en", "de"))
        self.assertEqual(trlib.translation_pair("en", "de-CH"), ("en", "de-CH"))

    def test_tr_run_refuses_a_german_source(self):
        root = support.project("german-source", "de", "en")
        support.write_docx(f"{root}/source/a.docx", ["Der Vertrag wurde unterzeichnet."])
        code, out = support.run("tr-run", root, f"{root}/source/a.docx")
        self.assertEqual(code, 2, out)
        self.assertIn("German source is not supported", out)


if __name__ == "__main__":
    unittest.main()
