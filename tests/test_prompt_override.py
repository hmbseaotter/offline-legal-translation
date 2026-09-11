"""A prompt file replacing the kit's: named, or refused when it has no
per-language blocks; and {when} conditions, read in any case and refused when
a value names nothing. Audit 2026-09-10: M-5, L-3."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import os
import unittest

import trlib


class PromptOverride(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mock = support.Mock()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def drop(self, name, prompt):
        root = support.project(name, "en", "de")
        support.write_text(f"{root}/prompts/translate.txt", prompt)
        support.write_docx(f"{root}/source/a.docx", ["The contract was signed."])
        return root, f"{root}/source/a.docx"

    def test_an_override_without_blocks_is_refused(self):
        root, src = self.drop("override-bare", "Translate {SRC} into {TGT}.\n{GLOSSARY}\n")
        code, out = support.run("tr-run", root, src, mock=self.mock)
        self.assertEqual(code, 2, out)
        self.assertIn("has no {when} blocks", out)
        self.assertFalse(os.path.exists(f"{root}/translated/a.docx"))

    def test_an_override_is_named(self):
        with open(os.path.join(support.KIT, "prompts", "translate.txt"), encoding="utf-8") as fh:
            kit = fh.read()
        root, src = self.drop("override-blocks", kit)
        code, out = support.run("tr-run", root, src, mock=self.mock)
        self.assertEqual(code, 0, out)
        self.assertIn(f"PROMPT OVERRIDE: {root}/prompts/translate.txt", out)
        self.assertIn(f"note: the prompt is {root}/prompts/translate.txt", out)


class Conditions(unittest.TestCase):

    def test_conditions_are_read_in_any_case(self):
        text = "A\n{when VARIANT=ch}\nSWISS\n{end}\n{when tgt=DE}\nGERMAN\n{end}\nZ\n"
        self.assertEqual(trlib._select_blocks(text, "en", "de-CH", "t"),
                         "A\nSWISS\nGERMAN\nZ\n")

    def test_a_value_that_names_nothing_is_refused(self):
        for cond in ("TGT=fr", "VARIANT=XX", "PAIR=en-fr", "SRC=de-CH"):
            with self.assertRaises(SystemExit, msg=cond):
                trlib._select_blocks(f"{{when {cond}}}\nX\n{{end}}\n", "en", "de", "t")


if __name__ == "__main__":
    unittest.main()
