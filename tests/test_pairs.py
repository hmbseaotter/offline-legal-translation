"""Language pairs: a German source is refused until language detection knows
German and German->English has rules of its own; an unknown language, or a
pair no model is chosen for, is refused before anything is drafted. Audit
2026-09-10: H-9, M-15, L-4, L-5."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import os
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

    def test_a_language_the_kit_does_not_know_is_refused(self):
        for src, tgt in [("en", "fr"), ("en", "xx"), ("en", "en")]:
            with self.assertRaises(SystemExit, msg=(src, tgt)):
                trlib.project_pair(src, tgt)

    def test_a_pair_with_no_model_is_refused_before_anything_is_listed(self):
        with self.assertRaises(SystemExit) as refused:
            trlib.translation_pair("sl", "de")
        self.assertIn("no model is chosen", str(refused.exception.code))
        root = support.project("no-model", "sl", "de")
        support.write_docx(f"{root}/source/a.docx", ["Pogodba je bila podpisana."])
        code, out = support.run("tr-run", root, "-n", f"{root}/source/a.docx")
        self.assertEqual(code, 2, out)
        self.assertNotIn("would", out)

    def test_a_swiss_glossary_follows_the_target_given(self):
        path = os.path.join(trlib.ROOT, "glossary", "project.tsv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        support.write_text(path, "Zzzstreet\tZzzstraße\n")
        try:
            self.assertIn(("Zzzstreet", "Zzzstrasse"), trlib.load_glossary("de-CH"))
            self.assertIn(("Zzzstreet", "Zzzstraße"), trlib.load_glossary("de"))
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
