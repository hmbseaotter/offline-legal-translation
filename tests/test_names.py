"""Deliverable names: files in one folder that would deliver under one name.
Audit 2026-09-10: P-1."""
import support  # noqa: F401  -- before trlib: sets the environment it reads

import calendar
import os
import unittest

import trlib


class TargetNames(unittest.TestCase):

    def test_without_a_collision_names_are_unchanged(self):
        names, clashes = trlib.target_names(["a/x.pdf", "a/y.txt", "b/x.docx", "t.xlsm"], "")
        self.assertEqual(names, {"a/x.pdf": "a/x.docx", "a/y.txt": "a/y.docx",
                                 "b/x.docx": "b/x.docx", "t.xlsm": "t.xlsx"})
        self.assertEqual(clashes, [])

    def test_on_a_collision_converted_files_keep_their_extension(self):
        names, clashes = trlib.target_names(
            ["a/x.docx", "a/x.pdf", "a/x.txt", "a/t.xlsx", "a/t.xlsm", "a/y.pdf"], "")
        self.assertEqual(names, {"a/x.docx": "a/x.docx", "a/x.pdf": "a/x.pdf.docx",
                                 "a/x.txt": "a/x.txt.docx", "a/t.xlsx": "a/t.xlsx",
                                 "a/t.xlsm": "a/t.xlsm.xlsx", "a/y.pdf": "a/y.docx"})
        self.assertEqual(clashes, [])

    def test_two_converted_files_both_keep_their_extensions(self):
        names, _clashes = trlib.target_names(["x.pdf", "x.txt"], "")
        self.assertEqual(names, {"x.pdf": "x.pdf.docx", "x.txt": "x.txt.docx"})

    def test_case_does_not_tell_names_apart(self):
        names, clashes = trlib.target_names(["x.DOCX", "x.pdf"], "")
        self.assertEqual(names["x.pdf"], "x.pdf.docx")
        self.assertEqual(clashes, [])
        _names, clashes = trlib.target_names(["X.docx", "x.docx"], "")
        self.assertEqual(clashes, [["X.docx", "x.docx"]])

    def test_suffix(self):
        names, _clashes = trlib.target_names(["x.docx", "x.pdf"], "_EN")
        self.assertEqual(names, {"x.docx": "x_EN.docx", "x.pdf": "x_EN.pdf.docx"})

    def test_a_name_still_shared_is_a_clash(self):
        _names, clashes = trlib.target_names(["x.pdf", "x.docx", "x.pdf.docx"], "")
        self.assertEqual(clashes, [["x.pdf", "x.pdf.docx"]])


class ThroughTrRun(unittest.TestCase):

    FIRST = "Prva pogodba je bila podpisana v Kranju."
    SECOND = "Druga pogodba je bila podpisana v Mariboru."

    @classmethod
    def setUpClass(cls):
        cls.mock = support.Mock()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def drop(self, name):
        root = support.project(name, "sl", "en")
        support.write_docx(f"{root}/source/a/s1.docx", [self.FIRST])
        support.write_text(f"{root}/source/a/s1.txt", self.SECOND + "\n")
        return root, [f"{root}/source/a/s1.docx", f"{root}/source/a/s1.txt"]

    def test_a_docx_and_a_txt_of_one_name_both_deliver(self):
        root, files = self.drop("docx-and-txt")
        code, out = support.run("tr-run", root, *files, mock=self.mock)
        self.assertEqual(code, 0, out)
        self.assertIn("translated: 2", out)
        self.assertEqual(support.read_docx(f"{root}/translated/a/s1.docx"),
                         [f"<<{self.FIRST}>>"])
        self.assertEqual(support.read_docx(f"{root}/translated/a/s1.txt.docx"),
                         [f"<<{self.SECOND}>>"])
        _code, out = support.run("tr-status", root)
        self.assertIn("translated: 2", out)
        self.assertIn("missing:    0", out)

    def test_a_deliverable_one_file_overwrote_is_redone(self):
        root, files = self.drop("overwritten")
        # As tr-run left a project before names were settled: both files
        # written to a/s1.docx, the .txt last, in the four-column table.
        support.write_docx(f"{root}/translated/a/s1.docx", [f"<<{self.SECOND}>>"])
        support.write_text(f"{root}/work/deliverables.tsv",
                           "path\tmodel\tprompt_version\twritten\n"
                           "a/s1.docx\tgams3:q8\tv6\t2026-09-01T10:00:00Z\n"
                           "a/s1.txt\tgams3:q8\tv6\t2026-09-01T10:01:00Z\n")
        # Saved when that row says it was written, as tr-run would have left
        # it: a later time reads as a translator's edit, which is kept.
        stamp = calendar.timegm((2026, 9, 1, 10, 1, 0))
        os.utime(f"{root}/translated/a/s1.docx", (stamp, stamp))
        _code, out = support.run("tr-status", root)
        self.assertIn("WRONG FILE", out)

        code, out = support.run("tr-run", root, *files, mock=self.mock)
        self.assertEqual(code, 0, out)
        self.assertIn("a/s1.docx holds the translation of a/s1.txt", out)
        self.assertEqual(support.read_docx(f"{root}/translated/a/s1.docx"),
                         [f"<<{self.FIRST}>>"])
        self.assertEqual(support.read_docx(f"{root}/translated/a/s1.txt.docx"),
                         [f"<<{self.SECOND}>>"])
        with open(f"{root}/work/deliverables.tsv", encoding="utf-8") as fh:
            self.assertIn("output", fh.readline().rstrip("\n").split("\t"))
        _code, out = support.run("tr-status", root)
        self.assertNotIn("WRONG FILE", out)

        code, out = support.run("tr-run", root, *files, mock=self.mock)
        self.assertIn("skipped: 2", out)

    def test_names_differing_only_in_case_are_refused(self):
        root = support.project("case-clash", "sl", "en")
        support.write_docx(f"{root}/source/a/X.docx", [self.FIRST])
        support.write_docx(f"{root}/source/a/x.docx", [self.SECOND])
        _code, out = support.run("tr-run", root, f"{root}/source/a/X.docx",
                                 f"{root}/source/a/x.docx", mock=self.mock)
        self.assertEqual(out.count("FAILED"), 2, out)
        self.assertIn("translated: 0", out)
        self.assertEqual(os.listdir(f"{root}/translated"), [])
        _code, out = support.run("tr-status", root)
        self.assertIn("CLASHING", out)


if __name__ == "__main__":
    unittest.main()
