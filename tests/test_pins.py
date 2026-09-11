"""What existing translation memory is keyed on: each pair's prompt version
and the prompt text it is sent. Invariant 7 derives the version from that
text, so a change here makes every row an existing memory holds for the pair
unreusable -- which may be intended, but must never be a side effect.
Audit 2026-09-10: regression set, item 1."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import hashlib
import unittest

import trlib


class Pins(unittest.TestCase):

    def test_prompt_versions(self):
        self.assertEqual(trlib.prompt_version("sl", "en"), "v6")
        self.assertEqual(trlib.prompt_version("en", "sl"), "v6")
        self.assertEqual(trlib.prompt_version("en", "de"), "p-86640e2a7d20")
        self.assertEqual(trlib.prompt_version("en", "de-CH"), "p-d9baa843461d")

    def test_rendered_prompts(self):
        for (s, t), want in {("en", "de"): "8084f261b1d588b0",
                             ("en", "de-CH"): "bd5e0ce6be4c33ee",
                             ("sl", "en"): "8f5e81528846cd61"}.items():
            got = hashlib.sha256(trlib.build_prompt(s, t, "").encode()).hexdigest()[:16]
            self.assertEqual(got, want, f"{s}-{t}")


if __name__ == "__main__":
    unittest.main()
