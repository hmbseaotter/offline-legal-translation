"""tr-refimport: a past project's originals and translations copied into
reference/, labelled as tr-ref reads them, with the archive left as it was."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import os
import shutil
import tempfile
import unittest

from test_references import D3, E3


def listing(top):
    return sorted(os.path.relpath(os.path.join(dp, f), top)
                  for dp, _dirs, files in os.walk(top) for f in files)


def archive(name, translations="out/356"):
    """An invented client's past project: (originals, translations)."""
    client = os.path.join(support.ROOT, "archive", name)
    originals, delivered = os.path.join(client, "in/356"), os.path.join(client, translations)

    def docx(top, rel, paragraphs):
        support.write_docx(os.path.join(top, rel), paragraphs)

    def text(top, rel, body):
        support.write_text(os.path.join(top, rel), body)
    docx(originals, "lease.docx", E3)
    docx(delivered, "lease_German.docx", D3)
    text(originals, "sub/terms.txt", "\n\n".join(E3[:4]) + "\n")
    docx(delivered, "sub/terms_German.txt.docx", D3[:4])
    docx(originals, "Pogodba 5.1.docx", E3[4:8])
    docx(delivered, "Pogodba 5.1_German.docx", D3[4:8])
    text(delivered, "Invoice 356.pdf", "not a translation\n")
    docx(originals, "letter_German.docx", ["Sehr geehrte Damen und Herren."])
    text(originals, "Notes.txt", "one\n")
    text(originals, "notes.txt", "two\n")
    text(originals, "old.doc", "saved by an old word processor\n")
    return originals, delivered


class RefImport(unittest.TestCase):

    def run_it(self, root, originals, translations, *args):
        return support.run("tr-refimport", root, originals, translations,
                            "--from", "en", "--to", "de", *args)

    def test_a_dry_run_lists_and_copies_nothing(self):
        root = support.project("refimport-dry", "en", "de")
        originals, translations = archive("dry")
        code, out = self.run_it(root, originals, translations)
        self.assertEqual(code, 0, out)
        self.assertEqual(listing(f"{root}/reference"), [])
        for line in ("Invoice 356.pdf   no language label",
                     "letter_German.docx   labelled de, among originals in en",
                     "Notes.txt   would share its name with 1 other file(s)",
                     "nothing copied"):
            self.assertIn(line, out)

    def test_any_two_folders_pair_and_nothing_is_overwritten(self):
        root = support.project("refimport", "en", "de")
        originals, translations = archive("apply", "Delivered 2019/356 final")
        before = listing(os.path.dirname(os.path.dirname(originals)))
        code, out = self.run_it(root, originals, translations, "--apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(listing(f"{root}/reference"), sorted([
            "356/Pogodba 5.1_English.docx", "356/Pogodba 5.1_German.docx",
            "356/lease_English.docx", "356/lease_German.docx", "356/old_English.doc",
            "356/sub/terms_English.txt", "356/sub/terms_German.txt.docx"]))
        self.assertEqual(listing(os.path.dirname(os.path.dirname(originals))), before)
        self.assertIn("pairs 3", out)
        self.assertIn("tr-ref cannot read 1 of them: .doc 1", out)

        code, out = self.run_it(root, originals, translations, "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("already at the destination", out)
        self.assertIn("copied 0 file(s)", out)

        code, out = support.run("tr-ref", root)
        self.assertEqual(code, 0, out)
        self.assertIn("3 reference pair(s)", out)

    def test_overlapping_folders_are_refused(self):
        root = support.project("refimport-overlap", "en", "de")
        originals, translations = archive("overlap")
        client = os.path.dirname(os.path.dirname(originals))
        code, out = self.run_it(root, client, translations, "--apply")
        self.assertNotEqual(code, 0, out)
        self.assertIn("overlap", out)
        self.assertEqual(listing(f"{root}/reference"), [])

    def test_the_copies_stay_inside_the_container(self):
        root = support.project("refimport-outside", "en", "de")
        originals, translations = archive("outside")
        outside = tempfile.mkdtemp(prefix="refimport-outside-")
        try:
            code, out = self.run_it(root, originals, translations, "--into", outside, "--apply")
            self.assertNotEqual(code, 0, out)
            self.assertIn("go inside the container", out)
            self.assertEqual(os.listdir(outside), [])
        finally:
            shutil.rmtree(outside, True)


if __name__ == "__main__":
    unittest.main()
