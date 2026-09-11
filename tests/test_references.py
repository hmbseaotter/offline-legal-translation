"""Reference translations: alignment, merging, extraction, and reuse through
tr-ref and tr-run. Audit 2026-09-10: H-3, H-4, M-7, M-8, M-9, M-10, M-11,
L-11, L-13, L-14."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import io
import os
import unittest
from contextlib import redirect_stderr

import trlib  # noqa: F401
import trref

# Invented sentence sets with a known correspondence. The first two carry no
# numbers at all, the third alternates numbered and unnumbered sentences, and
# the fourth has neighbours that share their numbers.
E1 = ["The Tenant shall pay the rent on time.",
      "The Tenant shall keep the premises clean.",
      "The Landlord shall carry out major repairs.",
      "The Tenant shall not keep pets without consent.",
      "Subletting requires the written consent of the Landlord.",
      "The Tenant shall report defects without delay.",
      "Structural alterations require the written consent of the Landlord.",
      "The Landlord may enter the premises after reasonable notice.",
      "The Tenant shall return the keys at the end of the lease.",
      "This lease is governed by the law of the place where the premises are located."]
D1 = ["Der Mieter hat die Miete pünktlich zu zahlen.",
      "Der Mieter hat die Räume sauber zu halten.",
      "Der Vermieter führt größere Reparaturen durch.",
      "Der Mieter darf ohne Zustimmung keine Haustiere halten.",
      "Die Untervermietung bedarf der schriftlichen Zustimmung des Vermieters.",
      "Der Mieter hat Mängel unverzüglich anzuzeigen.",
      "Bauliche Veränderungen bedürfen der schriftlichen Zustimmung des Vermieters.",
      "Der Vermieter darf die Räume nach angemessener Ankündigung betreten.",
      "Der Mieter hat die Schlüssel am Ende der Mietzeit zurückzugeben.",
      "Dieser Mietvertrag unterliegt dem Recht des Ortes, an dem sich die Räume befinden."]
E2 = ["Rent is due monthly.",
      "The Tenant shall pay all utility costs, including heating, water, electricity "
      "and waste collection, directly to the providers.",
      "Pets are not allowed.",
      "The Landlord shall maintain the roof, the facade and the common areas in good repair.",
      "Smoking is prohibited in the stairwell.",
      "The Tenant may install a satellite dish only with the prior written consent "
      "of the Landlord.",
      "Keys must not be copied.",
      "Noise must be kept to a minimum between ten in the evening and seven in the morning.",
      "The garden may be used by all tenants."]
D2 = ["Die Miete ist monatlich fällig.",
      "Der Mieter trägt sämtliche Nebenkosten, einschließlich Heizung, Wasser, Strom "
      "und Müllabfuhr, direkt gegenüber den Versorgern.",
      "Haustiere sind nicht erlaubt.",
      "Der Vermieter hält das Dach, die Fassade und die Gemeinschaftsflächen in gutem Zustand.",
      "Das Rauchen im Treppenhaus ist verboten.",
      "Der Mieter darf eine Satellitenschüssel nur mit vorheriger schriftlicher "
      "Zustimmung des Vermieters anbringen.",
      "Schlüssel dürfen nicht nachgemacht werden.",
      "Zwischen zweiundzwanzig Uhr abends und sieben Uhr morgens ist Lärm auf ein "
      "Mindestmaß zu beschränken.",
      "Der Garten darf von allen Mietern genutzt werden."]
E3 = ["The lease begins on 1 March 2024.",
      "The Tenant shall keep the premises clean.",
      "The monthly rent is 850 EUR.",
      "The rent is paid by bank transfer.",
      "The deposit of 2,550 EUR is held in a separate account.",
      "The deposit is returned when the Tenant leaves.",
      "Either party may give 3 months' notice.",
      "Notice must be given in writing.",
      "The Landlord repairs the roof within 14 days.",
      "Pets are not allowed.",
      "This lease is signed in 2 copies."]
D3 = ["Das Mietverhältnis beginnt am 1. März 2024.",
      "Der Mieter hat die Räume sauber zu halten.",
      "Die monatliche Miete beträgt 850 EUR.",
      "Die Miete wird per Überweisung bezahlt.",
      "Die Kaution von 2.550 EUR wird auf einem separaten Konto verwahrt.",
      "Die Kaution wird beim Auszug des Mieters zurückgezahlt.",
      "Jede Partei kann mit einer Frist von 3 Monaten kündigen.",
      "Die Kündigung bedarf der Schriftform.",
      "Der Vermieter repariert das Dach innerhalb von 14 Tagen.",
      "Haustiere sind nicht erlaubt.",
      "Dieser Mietvertrag wird in 2 Ausfertigungen unterzeichnet."]
E4 = ["The cleaning fee is 50 EUR.",
      "The key deposit is 50 EUR.",
      "The parking fee is 50 EUR.",
      "The Tenant shall pay the rent on time.",
      "The Tenant shall keep the premises clean.",
      "The notice period is 3 months.",
      "The lease is signed on 2 June 2024.",
      "Subletting requires the Landlord's consent.",
      "The rent is reviewed after 12 months."]
D4 = ["Die Reinigungsgebühr beträgt 50 EUR.",
      "Die Schlüsselkaution beträgt 50 EUR.",
      "Die Parkgebühr beträgt 50 EUR.",
      "Der Mieter hat die Miete pünktlich zu zahlen.",
      "Der Mieter hat die Räume sauber zu halten.",
      "Die Kündigungsfrist beträgt 3 Monate.",
      "Der Mietvertrag wird am 2. Juni 2024 unterzeichnet.",
      "Die Untervermietung bedarf der Zustimmung des Vermieters.",
      "Die Miete wird nach 12 Monaten überprüft."]
SETS = [("no numbers 1", E1, D1), ("no numbers 2", E2, D2),
        ("alternating", E3, D3), ("shared numbers", E4, D4)]
NOTE = "Diese Klausel gilt sinngemäß auch für Untermieter."


def perturbations(E, D):
    """The document pair as it is, and with every sentence omitted from either
    side, a note inserted after every sentence, every neighbouring pair
    swapped on either side, and an omission balanced by a note further on."""
    n = len(E)
    yield "clean", E, D
    for k in range(n):
        yield f"omit target {k}", E, D[:k] + D[k + 1:]
        yield f"omit source {k}", E[:k] + E[k + 1:], D
        yield f"note after {k}", E, D[:k + 1] + [NOTE] + D[k + 1:]
        if k < n - 1:
            yield f"swap targets {k}", E, D[:k] + [D[k + 1], D[k]] + D[k + 2:]
            yield f"swap sources {k}", E[:k] + [E[k + 1], E[k]] + E[k + 2:], D
        if k < n - 3:
            yield f"omit {k}, note after {k + 2}", E, D[:k] + D[k + 1:k + 3] + [NOTE] + D[k + 3:]


class Alignment(unittest.TestCase):

    def test_no_wrong_pair_is_kept_for_reuse(self):
        wrong, alignments = [], 0
        for name, E, D in SETS:
            truth = dict(zip(E, D))
            for kind, src, tgt in perturbations(E, D):
                for by_paragraph in (True, False):
                    kept, _rejected = trref.align_document(src, tgt, by_paragraph)
                    alignments += 1
                    wrong += [(name, kind, by_paragraph, s, t) for s, t, confirmed
                              in kept if confirmed and truth.get(s) != t]
        self.assertGreater(alignments, 400)
        self.assertEqual(wrong, [])

    def test_a_numbered_document_keeps_its_pairs(self):
        for by_paragraph in (True, False):
            kept, _rejected = trref.align_document(E3, D3, by_paragraph)
            self.assertEqual(kept, [(e, d, True) for e, d in zip(E3, D3)])

    def test_shared_numbers_confirm_nothing(self):
        kept, rejected = trref.align_document(E4, D4)
        self.assertEqual(kept, [(e, d, i >= 5) for i, (e, d) in enumerate(zip(E4, D4))])
        self.assertEqual(rejected, [])

    def test_a_document_without_numbers_is_only_offered(self):
        kept, _rejected = trref.align_document(E1, D1)
        self.assertEqual(kept, [(e, d, False) for e, d in zip(E1, D1)])


def row(doc, tgt, date="2024-01-01T00:00:00Z", offered=()):
    return trref.Row("en-de", doc, tgt, int(not offered), date, "Word last saved",
                     offered)


class Merging(unittest.TestCase):

    def test_case_sign_percent_and_section_sign_are_differences(self):
        key = trref.rendering_key
        for a, b in [("Wenn Sie kündigen.", "Wenn sie kündigen."),
                     ("Der Saldo beträgt -250,00 EUR.", "Der Saldo beträgt 250,00 EUR."),
                     ("Die Zinsen betragen 5 %.", "Die Zinsen betragen 5."),
                     ("gemäß § 5", "gemäß 5"), ("5.1", "51")]:
            self.assertNotEqual(key(a), key(b), (a, b))
        self.assertEqual(key("Der Mieter zahlt."), key("Der Mieter zahlt"))
        self.assertEqual(key("Rhein-Main"), key("Rhein Main"))

    def test_renderings_differing_in_case_are_offered(self):
        text = trref.resolve(
            [row("d1", "Wenn Sie den Mietvertrag kündigen, wird die Kaution zurückgezahlt."),
             row("d2", "Wenn sie den Mietvertrag kündigen, wird die Kaution zurückgezahlt.",
                 "2023-01-01T00:00:00Z")],
            "en-de", "If you terminate the lease, the deposit is returned.")[0]
        self.assertTrue(text.startswith(trref.OPTIONS_MARK), text)

    def test_renderings_differing_in_sign_are_offered(self):
        text = trref.resolve([row("d1", "Der Saldo beträgt -250,00 EUR."),
                              row("d2", "Der Saldo beträgt 250,00 EUR."),
                              row("d3", "Der Saldo beträgt 250,00 EUR.")],
                             "en-de", "The balance is -250.00 EUR.")[0]
        self.assertEqual(text, "REF_OPTIONS [[Der Saldo beträgt 250,00 EUR.]] | "
                               "[[Der Saldo beträgt -250,00 EUR.]]")

    def test_an_unconfirmed_rendering_is_offered_unless_a_copy_is_confirmed(self):
        pets = "Haustiere sind nicht erlaubt."
        unconfirmed = row("d1", pets, offered=(trref.UNCONFIRMED,))
        self.assertEqual(trref.resolve([unconfirmed], "en-de", "Pets are not allowed.")[0],
                         f"REF_OPTIONS [[{pets}]] (unconfirmed)")
        self.assertEqual(trref.resolve([unconfirmed, row("d2", pets)], "en-de",
                                       "Pets are not allowed.")[0], pets)


class Hyphenation(unittest.TestCase):

    def test_before_a_capital_the_hyphen_stays(self):
        self.assertEqual(trref._blocks("Die Räume liegen im Rhein-\nMain-Gebiet.", "de"),
                         ["Die Räume liegen im Rhein-Main-Gebiet."])
        self.assertEqual(trref._blocks("Articles 5-\n10 apply.", "en"),
                         ["Articles 5-10 apply."])

    def test_before_lower_case_the_join_is_unsure(self):
        for text, lang, want in [
                ("The Tenant is self-\nemployed.", "en", "The Tenant is self-employed."),
                ("Das Verwaltungs-  \n   gericht entscheidet.", "de",
                 "Das Verwaltungsgericht entscheidet.")]:
            [block] = trref._blocks(text, lang)
            self.assertEqual(trref.settle(block, block),
                             (want, want, (trref.HYPHENATION,)))

    def test_an_unsure_rendering_is_offered(self):
        text = trref.resolve([row("d1", "Der Mieter ist selbstständig.",
                                  offered=(trref.HYPHENATION,))],
                             "en-de", "The Tenant is self-employed.")[0]
        self.assertEqual(text, "REF_OPTIONS [[Der Mieter ist selbstständig.]] (hyphenation)")

    def test_tags_accumulate(self):
        self.assertEqual(trref.settle("a", "b" + trref.UNSURE + "c", (trref.OCR,)),
                         ("a", "bc", (trref.OCR, trref.HYPHENATION)))


class OlderRules(unittest.TestCase):

    def test_pairs_aligned_under_older_rules_are_not_reused(self):
        db = trref.open_store()
        db.execute("INSERT INTO pairs (direction, doc, src, src_norm, tgt, how, reusable)"
                   " VALUES ('en-de', 'old', 'Rule 1 applies.', 'Rule 1 applies.',"
                   " 'Regel 1 gilt.', 'docx', 1)")
        db.execute("INSERT INTO docs (direction, doc, signature, kept, rejected)"
                   " VALUES ('en-de', 'old', '120:1700000000|130:1700000000', 1, '')")
        db.commit()
        try:
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(trref.load_references(), {})
            self.assertIn("older rules", err.getvalue())
            db.execute("UPDATE docs SET signature = ?",
                       (f"a{trref.ALIGN_VERSION}|0|0",))
            db.commit()
            self.assertIn("Rule 1 applies.", trref.load_references()["en-de"])
        finally:
            db.execute("DELETE FROM pairs")
            db.execute("DELETE FROM docs")
            db.commit()
            db.close()


    def test_a_pair_stored_before_tags_is_offered_for_ocr(self):
        db = trref.open_store()
        db.execute("INSERT INTO pairs (direction, doc, src, src_norm, tgt, how, reusable)"
                   " VALUES ('en-de', 'scan', 'Rule 2 applies.', 'Rule 2 applies.',"
                   " 'Regel 2 gilt.', 'docx/pdf-ocr', 0)")
        db.execute("INSERT INTO docs (direction, doc, signature, kept, rejected)"
                   " VALUES ('en-de', 'scan', ?, 1, '')", (f"a{trref.ALIGN_VERSION}|0|0",))
        db.commit()
        try:
            [r] = trref.load_references()["en-de"]["Rule 2 applies."]
            self.assertEqual(r.offered, (trref.OCR,))
            self.assertEqual(trref.resolve([r], "en-de", "Rule 2 applies.")[0],
                             "REF_OPTIONS [[Regel 2 gilt.]] (OCR)")
        finally:
            db.execute("DELETE FROM pairs")
            db.execute("DELETE FROM docs")
            db.commit()
            db.close()


def pairs_tsv(root):
    with open(os.path.join(root, "work", "reference", "pairs.tsv"), encoding="utf-8") as fh:
        return fh.read()


class ThroughTheTools(unittest.TestCase):
    """tr-ref and tr-run against throwaway projects."""

    EN = ["The Tenant shall clean the stairwell on 2 days each week.",
          "The front door is locked every night at 22 o'clock.",
          "Bicycles may be stored in room 4 of the basement.",
          "Waste is collected on 3 fixed days per month.",
          "The laundry room is open for 12 hours every day.",
          "Guests may stay for up to 14 nights per year.",
          "Repairs above 500 EUR require the consent of the Landlord."]
    DE = ["Der Mieter hat das Treppenhaus an 2 Tagen jeder Woche zu reinigen.",
          "Die Haustür wird jede Nacht um 22 Uhr abgeschlossen.",
          "Fahrräder dürfen in Raum 4 des Kellers abgestellt werden.",
          "Der Abfall wird an 3 festen Tagen im Monat abgeholt.",
          "Die Waschküche ist täglich 12 Stunden geöffnet.",
          "Gäste dürfen bis zu 14 Nächte im Jahr bleiben.",
          "Reparaturen über 500 EUR bedürfen der Zustimmung des Vermieters."]

    def test_a_replaced_pdf_is_read_again(self):
        root = support.project("replaced-pdf", "en", "de")
        support.write_docx(f"{root}/reference/house/rules_English.docx", self.EN)
        pdf = f"{root}/reference/house/rules_German.pdf"
        support.write_pdf(pdf, self.DE)
        code, out = support.run("tr-ref", root)
        self.assertEqual(code, 0, out)
        self.assertIn(self.DE[0], pairs_tsv(root))

        corrected = "Das Treppenhaus reinigt der Mieter an 2 Tagen pro Woche."
        support.write_pdf(pdf, [corrected] + self.DE[1:])
        code, out = support.run("tr-ref", root)
        self.assertEqual(code, 0, out)
        self.assertIn(corrected, pairs_tsv(root))
        self.assertNotIn(self.DE[0], pairs_tsv(root))
        self.assertTrue(any(".replaced-" in f for f in os.listdir(f"{root}/work/ocr")))

    def test_an_unreadable_reference_takes_its_sentences_with_it(self):
        root = support.project("unreadable", "en", "de")
        english = f"{root}/reference/lease/lease_English.docx"
        support.write_docx(english, E3)
        support.write_docx(f"{root}/reference/lease/lease_German.docx", D3)
        code, out = support.run("tr-ref", root)
        self.assertEqual(code, 0, out)
        self.assertIn(D3[0], pairs_tsv(root))

        support.write_text(english, "not a zip file")
        code, out = support.run("tr-ref", root)
        self.assertEqual(code, 1, out)
        self.assertIn("FAILED", out)
        self.assertNotIn(D3[0], pairs_tsv(root))

    def test_a_reference_missing_a_clause_lends_no_wrong_sentence(self):
        root = support.project("omitted-clause", "en", "de")
        support.write_docx(f"{root}/reference/lease/lease_English.docx", E3)
        support.write_docx(f"{root}/reference/lease/lease_German.docx", D3[1:])
        support.write_docx(f"{root}/source/s.docx", E3[:4])
        code, out = support.run("tr-ref", root)
        self.assertEqual(code, 0, out)
        mock = support.Mock()
        try:
            code, out = support.run("tr-run", root, f"{root}/source/s.docx", mock=mock)
        finally:
            mock.stop()
        self.assertEqual(code, 0, out)
        got = support.read_docx(f"{root}/translated/s.docx")
        self.assertEqual(len(got), 4, got)
        for src, want, draft in zip(E3, D3, got):
            # The translator's rendering, a model draft, or a visible offer --
            # never another sentence's translation passed off as this one's.
            self.assertTrue(draft in (want, f"<<{src}>>")
                            or (draft.startswith("REF_OPTIONS [[")
                                and draft.endswith("(unconfirmed)")), draft)
        self.assertEqual(got[2], D3[2])

    def test_a_reference_without_numbers_is_offered(self):
        root = support.project("offered", "en", "de")
        support.write_docx(f"{root}/reference/lease/lease_English.docx", E1)
        support.write_docx(f"{root}/reference/lease/lease_German.docx", D1)
        support.write_docx(f"{root}/source/s.docx", E1[:2])
        code, out = support.run("tr-ref", root)
        self.assertEqual(code, 0, out)
        self.assertIn("(10 unconfirmed: offered)", out)
        mock = support.Mock()
        try:
            code, out = support.run("tr-run", root, f"{root}/source/s.docx", mock=mock)
            self.assertEqual(mock.requests(), [])
        finally:
            mock.stop()
        self.assertEqual(code, 0, out)
        self.assertEqual(support.read_docx(f"{root}/translated/s.docx"),
                         [f"REF_OPTIONS [[{d}]] (unconfirmed)" for d in D1[:2]])

    def test_a_germany_reference_reaches_a_swiss_draft_in_swiss_form(self):
        root = support.project("swiss-offer", "en", "de-CH")
        en = ["The deposit of 1,250.00 EUR is paid according to clause 4.",
              "The keys are handed over at 14:30 on 2 May 2024.",
              "Room 7 is used for storage."]
        de = ["Die Kaution von 1.250,00 EUR wird gemäß Ziffer 4 gezahlt.",
              "Die Schlüssel werden am 2. Mai 2024 um 14:30 Uhr übergeben.",
              "Raum 7 dient als Lager."]
        swiss = ["Die Kaution von 1250.00 EUR wird gemäss Ziffer 4 gezahlt.",
                 "Die Schlüssel werden am 2. Mai 2024 um 14.30 Uhr übergeben."]
        support.write_docx(f"{root}/reference/lease/lease_English.docx", en)
        support.write_docx(f"{root}/reference/lease/lease_German.docx", de)
        support.write_docx(f"{root}/source/s.docx", en[:2])
        code, out = support.run("tr-ref", root)
        self.assertEqual(code, 0, out)
        for text in swiss:
            self.assertIn(f"\t{text}\tdocx\toption\n", pairs_tsv(root))
        mock = support.Mock()
        try:
            code, out = support.run("tr-run", root, f"{root}/source/s.docx", mock=mock)
            self.assertEqual(mock.requests(), [])
        finally:
            mock.stop()
        self.assertEqual(code, 0, out)
        self.assertEqual(support.read_docx(f"{root}/translated/s.docx"),
                         [f"REF_OPTIONS [[{t}]] (de-DE)" for t in swiss])

    def test_formats_it_cannot_read_are_listed_and_rejections_are_kept(self):
        root = support.project("formats", "en", "de")
        lease_de = f"{root}/reference/lease/lease_German.docx"
        rules_de = f"{root}/reference/house/rules_German.docx"
        support.write_text(f"{root}/reference/old/notice_English.doc", "not readable here")
        support.write_docx(f"{root}/reference/lease/lease_English.docx", E3)
        support.write_docx(lease_de, D3[:4] + [D3[4].replace("2.550", "3.550")] + D3[5:])
        support.write_docx(f"{root}/reference/house/rules_English.docx", self.EN)
        support.write_docx(rules_de, self.DE[:6] + [self.DE[6].replace("500", "600")])

        def rejected():
            with open(f"{root}/work/reference/rejected.tsv", encoding="utf-8") as fh:
                return fh.read()
        code, out = support.run("tr-ref", root)
        self.assertEqual(code, 0, out)
        self.assertIn("1 file(s) in a format tr-ref cannot read", out)
        self.assertIn("old/notice_English.doc", out)
        self.assertIn("3.550 EUR", rejected())
        self.assertIn("600 EUR", rejected())

        # The rules change and the lease does not: the lease's rejection stays.
        support.write_docx(rules_de, self.DE[:2] + [self.DE[2].replace("4", "5")] + self.DE[3:])
        code, out = support.run("tr-ref", root)
        self.assertEqual(code, 0, out)
        self.assertIn("3.550 EUR", rejected())
        self.assertIn("Raum 5", rejected())
        self.assertNotIn("600 EUR", rejected())

        # The lease is removed, and its rejection with it.
        os.remove(lease_de)
        code, out = support.run("tr-ref", root)
        self.assertEqual(code, 0, out)
        self.assertNotIn("3.550 EUR", rejected())


class FirstMentionOfReferences(unittest.TestCase):

    def test_a_reference_is_written_as_it_is_and_counts_as_a_mention(self):
        first = trlib.FirstMention("sl-en")
        src, tgt = first.pairs[0]
        options = f"REF_OPTIONS [[The {tgt} ruled.]] | [[It ruled.]]"
        self.assertEqual(first.apply(options, reference=True), options)
        self.assertEqual(first.apply(f"The {tgt} ruled again."), f"The {tgt} ruled again.")
        self.assertEqual(trlib.FirstMention("sl-en").apply(f"The {tgt} ruled."),
                         f"The {src} ({tgt}) ruled.")

    def test_what_a_reference_gave_is_known(self):
        saved = trlib._REFERENCES
        trlib._REFERENCES = {"en-de": {"Rule 9 applies.": [row("d9", "Regel 9 gilt.")]}}
        try:
            self.assertEqual(trlib.reference_translation("Rule 9 applies.", "en-de"),
                             "Regel 9 gilt.")
            self.assertIn("Regel 9 gilt.", trlib.REFERENCE_TEXTS)
        finally:
            trlib._REFERENCES = saved


if __name__ == "__main__":
    unittest.main()
