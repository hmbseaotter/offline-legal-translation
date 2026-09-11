"""Fixes reaching work already done: memory rows finished again when read,
and deliverables drafted again when anything that made them has changed.
Audit 2026-09-10: H-1, H-2, M-6."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import os
import unittest

import trlib

NBSP, WJ = "\u00a0", "\u2060"

class Refinish(unittest.TestCase):
    """Memory rows from before a finishing fix, read back with nothing asked
    of the model."""

    @classmethod
    def setUpClass(cls):
        cls.mock = support.Mock()
        cls.ollama, trlib.OLLAMA = trlib.OLLAMA, cls.mock.url

    @classmethod
    def tearDownClass(cls):
        trlib.OLLAMA = cls.ollama
        cls.mock.stop()

    def read_back(self, src, old, s, t):
        trlib.tm_put(src, old, f"{s}-{t}")
        before = len(self.mock.requests())
        got = trlib.ollama_translate(src, s, t)
        self.assertEqual(self.mock.requests()[before:], [])
        self.assertEqual(trlib.tm_get(src, f"{s}-{t}"), got)
        return got

    def test_a_sentence_final_amount_is_converted(self):
        self.assertEqual(self.read_back("Znesek kupnine znaša 12.450,00.",
                                        "The purchase price is 12.450,00.", "sl", "en"),
                         "The purchase price is 12,450.00.")

    def test_a_reference_written_as_a_decimal_is_put_back(self):
        self.assertEqual(self.read_back("See Section 5.10 of the lease.",
                                        "Siehe Abschnitt 5,10 des Mietvertrags.", "en", "de"),
                         "Siehe Abschnitt 5.10 des Mietvertrags.")
        self.assertEqual(self.read_back("The meeting starts at 10.30 am.",
                                        "Die Sitzung beginnt um 10,30 Uhr.", "en", "de-CH"),
                         "Die Sitzung beginnt um 10.30 Uhr.")

    def test_whole_francs_are_held_together(self):
        self.assertEqual(self.read_back("The fee is CHF 20.",
                                        "Die Gebühr beträgt Fr. 20.–.", "en", "de-CH"),
                         f"Die Gebühr beträgt Fr.{NBSP}20.{WJ}–.")

    def test_batched_rows_are_finished_too(self):
        src = "Plačano je bilo 1.250,50."
        trlib.tm_put(src, "It was paid 1.250,50.", "sl-en")
        self.assertEqual(trlib.ollama_translate_many([src], "sl", "en"),
                         ["It was paid 1,250.50."])

    def test_a_quantity_the_source_also_has_stays_a_decimal(self):
        src = "Clause 3.2 sets interest at 3.2 per cent."
        draft = "Klausel 3.2 setzt die Zinsen auf 3,2 Prozent fest."
        self.assertEqual(trlib.finish_draft(src, draft, "en", "de"), draft)


class Redo(unittest.TestCase):
    """tr-run and tr-status on a project, changing one thing at a time."""

    SENTENCES = ["Pogodbo je podpisal prodajalec.", "Kupnina je bila plačana v celoti."]

    @classmethod
    def setUpClass(cls):
        cls.mock = support.Mock()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        self.root = support.project(f"redo-{self._testMethodName}", "sl", "en")
        self.src = f"{self.root}/source/a.docx"
        self.out = f"{self.root}/translated/a.docx"
        support.write_docx(self.src, self.SENTENCES)

    def tr_run(self, *files):
        code, out = support.run("tr-run", self.root, *(files or [self.src]), mock=self.mock)
        self.assertEqual(code, 0, out)
        return out

    def drafted(self):
        self.assertIn("translated: 1", self.tr_run())
        self.assertIn("skipped: 1", self.tr_run())

    def column(self, key, value):
        tsv = f"{self.root}/work/deliverables.tsv"
        with open(tsv, encoding="utf-8") as fh:
            lines = [ln.rstrip("\n").split("\t") for ln in fh]
        i = lines[0].index(key)
        for cols in lines[1:]:
            cols[i] = value
        support.write_text(tsv, "".join("\t".join(c) + "\n" for c in lines))

    def test_a_glossary_term_redraws_only_its_sentences(self):
        self.drafted()
        support.write_text(f"{self.root}/glossary/project.tsv", "prodajalec\tthe Vendor\n")
        before = len(self.mock.requests())
        out = self.tr_run()
        self.assertIn("the glossary changed", out)
        self.assertIn("translated: 1", out)
        self.assertEqual([r["prompt"] for r in self.mock.requests()[before:]],
                         [self.SENTENCES[0]])

    def test_a_reference_kept_later(self):
        self.drafted()
        support.write_docx(f"{self.root}/reference/r/contract_Slovene.docx", self.SENTENCES)
        support.write_docx(f"{self.root}/reference/r/contract_English.docx",
                           ["The Vendor signed the contract.", "The price was paid in full."])
        code, out = support.run("tr-ref", self.root)
        self.assertEqual(code, 0, out)
        out = self.tr_run()
        self.assertIn("the reference translations changed", out)
        self.assertEqual(support.read_docx(self.out),
                         ["REF_OPTIONS [[The Vendor signed the contract.]] (unconfirmed)",
                          "REF_OPTIONS [[The price was paid in full.]] (unconfirmed)"])

    def test_a_source_replaced_with_its_time_kept(self):
        self.drafted()
        st = os.stat(self.src)
        support.write_docx(self.src, [self.SENTENCES[0], "Kupnina je bila plačana delno."])
        os.utime(self.src, (st.st_atime, st.st_mtime))
        self.assertIn("the source file changed", self.tr_run())

    def test_the_drafting_code(self):
        self.drafted()
        self.column("drafting", "0" * 16)
        self.assertIn("the kit's drafting code changed", self.tr_run())

    def test_a_row_from_before(self):
        self.drafted()
        tsv = f"{self.root}/work/deliverables.tsv"
        with open(tsv, encoding="utf-8") as fh:
            five = ["\t".join(ln.rstrip("\n").split("\t")[:5]) for ln in fh]
        support.write_text(tsv, "\n".join(five) + "\n")
        out = self.tr_run()
        self.assertIn("written before tr-run recorded", out)
        self.assertIn("translated: 1", out)

    def test_an_edited_deliverable_is_kept(self):
        self.drafted()
        support.write_docx(self.out, ["Corrected by the translator."])
        self.assertIn("skipped: 1", self.tr_run())
        support.write_text(f"{self.root}/glossary/project.tsv", "prodajalec\tthe Vendor\n")
        out = self.tr_run()
        self.assertIn("kept   [1/1] a.docx", out)
        self.assertIn("the glossary changed", out)
        self.assertEqual(support.read_docx(self.out), ["Corrected by the translator."])
        _code, status = support.run("tr-status", self.root)
        self.assertIn("EDITED", status)
        os.rename(self.out, self.out + ".mine")
        self.assertIn("translated: 1", self.tr_run())

    def test_a_text_layer_read_again(self):
        pdf = f"{self.root}/source/scan.pdf"
        support.write_pdf(pdf, support.SLOVENE_LINES)
        self.assertIn("translated: 1", self.tr_run(pdf))
        self.assertIn("skipped: 1", self.tr_run(pdf))
        with open(f"{self.root}/work/ocr/scan.txt", "a", encoding="utf-8") as fh:
            fh.write("\nStranki sta pogodbo podpisali.\n")
        out = self.tr_run(pdf)
        self.assertIn("the text layer changed", out)
        self.assertIn("translated: 1", out)

    def test_tr_status_reports_what_changed(self):
        self.drafted()
        support.write_text(f"{self.root}/glossary/project.tsv", "prodajalec\tthe Vendor\n")
        _code, out = support.run("tr-status", self.root)
        self.assertIn("STALE", out)
        self.assertIn("a.docx   (the glossary changed)", out)


if __name__ == "__main__":
    unittest.main()
