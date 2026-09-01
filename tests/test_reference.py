#!/usr/bin/env python3
"""
The reference sheet (study S9) — one note, two tiers.

The tiers are the whole design, so most of what is worth pinning is about
them: that `exam` is a *filter* over the same entries rather than a second
document, that a sheet with no exam tier is refused (the simplified view is
the one with a hard constraint, and an empty one is not a simplification), and
that the budget is enforced rather than suggested — a "fits on one sheet" that
does not fit is the single promise this tier makes.

The rest is the usual: structure is checked, content is not. Whether an
equation is *correct* is Zach's judgement at review, exactly as with a module.
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime"))

import lesson as ln  # noqa: E402

FM = ("---\n"
      "type: reference\n"
      "course: AA-210\n"
      "tags: [guide]\n"
      "---\n\n")

OK = FM + """## Vectors

### Dot product
kind:: equation
tier:: exam
$$\\mathbf{A}\\cdot\\mathbf{B} = \\lVert\\mathbf{A}\\rVert\\lVert\\mathbf{B}\\rVert\\cos\\theta$$
Zero means perpendicular.

### Scalar triple product
kind:: equation
tier:: full
$$\\mathbf{A}\\cdot(\\mathbf{B}\\times\\mathbf{C})$$
The volume of the parallelepiped.

## Constants

### Standard gravity
kind:: constant
tier:: exam
$g = 9.81\\ \\mathrm{m/s^2}$ near the Earth's surface.
"""


class TestTheGrammar(unittest.TestCase):
    def test_a_plausible_sheet_validates(self):
        self.assertEqual(ln.validate_reference(OK), [])

    def test_sections_and_entries_come_back(self):
        d = ln.parse_reference(OK)
        self.assertEqual([s["title"] for s in d["sections"]],
                         ["Vectors", "Constants"])
        self.assertEqual(len(ln.reference_entries(d)), 3)

    def test_the_body_survives_the_keys(self):
        d = ln.parse_reference(OK)
        first = ln.reference_entries(d)[0]
        self.assertIn("perpendicular", first["body"])
        self.assertNotIn("tier::", first["body"])

    def test_a_key_below_the_body_is_prose(self):
        """`kind::` and `tier::` are a header, not a syntax that can appear
        anywhere — otherwise a sentence *about* the tiers rewrites the entry."""
        d = ln.parse_reference(FM + "## S\n\n### E\nkind:: definition\n"
                                    "tier:: exam\nThe word tier:: exam is prose here.\n")
        e = ln.reference_entries(d)[0]
        self.assertEqual(e["tier"], "exam")
        self.assertIn("prose here", e["body"])


class TestTheTiers(unittest.TestCase):
    def test_exam_is_a_subset_of_full(self):
        d = ln.parse_reference(OK)
        full = {e["title"] for e in ln.reference_entries(d, "full")}
        exam = {e["title"] for e in ln.reference_entries(d, "exam")}
        self.assertTrue(exam < full, "exam must be a strict subset")
        self.assertEqual(exam, {"Dot product", "Standard gravity"})

    def test_the_detailed_view_is_everything(self):
        """Not the complement of the simplified one — a reader on the detailed
        tier wants the whole sheet, including what is also on the exam sheet."""
        d = ln.parse_reference(OK)
        self.assertEqual(len(ln.reference_entries(d, "full")),
                         len(ln.reference_entries(d)))

    def test_a_sheet_with_no_exam_tier_is_refused(self):
        errs = ln.validate_reference(OK.replace("tier:: exam", "tier:: full"))
        self.assertTrue(any("no exam-tier" in e for e in errs), errs)

    def test_the_budget_is_enforced(self):
        fat = FM + "## S\n\n### Long one\nkind:: definition\ntier:: exam\n" \
            + ("word " * (ln.EXAM_BUDGET // 5 + 200)) + "\n"
        errs = ln.validate_reference(fat)
        self.assertTrue(any("over the" in e for e in errs), errs)

    def test_size_counts_only_the_exam_tier(self):
        d = ln.parse_reference(OK)
        exam_only = sum(len(e["title"]) + len(e["body"]) + 2
                        for e in ln.reference_entries(d, "exam"))
        self.assertEqual(ln.reference_size(d), exam_only)


class TestItRefuses(unittest.TestCase):
    def refused(self, text: str, needle: str):
        errs = ln.validate_reference(text)
        self.assertTrue(any(needle in e for e in errs),
                        f"expected {needle!r} in {errs}")

    def test_an_unknown_kind(self):
        self.refused(OK.replace("kind:: constant", "kind:: mnemonic"), "kind::")

    def test_an_unknown_tier(self):
        self.refused(OK.replace("tier:: full", "tier:: medium"), "tier::")

    def test_a_duplicate_title(self):
        self.refused(OK.replace("Scalar triple product", "Dot product"),
                     "duplicate")

    def test_an_entry_with_no_body(self):
        self.refused(FM + "## S\n\n### Empty\nkind:: definition\ntier:: exam\n",
                     "no body")

    def test_a_section_with_no_entries(self):
        self.refused(OK + "\n## Orphan section\n", "no entries")

    def test_the_wrong_type(self):
        self.refused(OK.replace("type: reference", "type: module"), "type is")

    def test_content_before_the_first_entry(self):
        self.refused(FM + "## S\n\nloose prose\n\n### E\nkind:: definition\n"
                          "tier:: exam\nbody\n",
                     "content before the first")


class TestLoading(unittest.TestCase):
    """`load_reference` against a real folder, including the privacy split.

    This exists because the first version read the split's return backwards.
    It hands back what is **sealed** first, not what is allowed — so the normal
    case, an empty set meaning nothing is sealed, was read as "nothing is
    permitted" and every reference sheet 404'd through the API while loading
    perfectly in a unit test that passed no split at all.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        folder = self.vault / "02-Areas" / "Academics" / "AA-210"
        folder.mkdir(parents=True)
        (folder / "aa-210-reference.md").write_text(OK, encoding="utf-8")
        self.rel = "02-Areas/Academics/AA-210/aa-210-reference.md"

    def tearDown(self):
        self.tmp.cleanup()

    def test_nothing_sealed_means_it_loads(self):
        """The bug, pinned: an empty *sealed* set is the normal case and must
        not read as an empty *allowed* set."""
        d = ln.load_reference(self.vault, "AA-210",
                              split=lambda _v, rels: (set(), set(rels)))
        self.assertIsNotNone(d, "an empty sealed set must not hide the sheet")
        self.assertEqual(d["file"], self.rel)
        self.assertEqual(d["counts"], {"all": 3, "exam": 2})
        self.assertEqual(d["exam_budget"], ln.EXAM_BUDGET)

    def test_the_default_split_fails_closed(self):
        """No split means `_default_split`, which seals everything when the
        privacy module cannot answer for a vault — the loud direction, and the
        same one `scan()` takes. A temp vault is exactly that case."""
        self.assertIsNone(ln.load_reference(self.vault, "AA-210"))

    def test_a_sealed_sheet_is_withheld(self):
        d = ln.load_reference(self.vault, "AA-210",
                              split=lambda _v, rels: (set(rels), set()))
        self.assertIsNone(d)

    def test_a_course_without_one(self):
        self.assertIsNone(ln.load_reference(self.vault, "CSE-999"))


FIGURE_OK = ('figure:: two pointers closing in\n'
             '<svg viewBox="0 0 100 40" xmlns="http://www.w3.org/2000/svg">\n'
             '  <circle cx="20" cy="20" r="8" fill="none" stroke="currentColor"/>\n'
             '</svg>\n')


class TestFigures(unittest.TestCase):
    """An entry may carry one figure — the module segment's own grammar, third
    home. What is worth pinning: the SVG never leaks into the body, the same
    allow-list holds, and the exam budget charges a figure its page space."""

    def sheet(self, extra: str) -> str:
        return OK + "\n## Drawn\n\n### With a picture\nkind:: definition\n" \
                    "tier:: full\nSome prose.\n" + extra

    def test_a_figure_parses_out_of_the_body(self):
        d = ln.parse_reference(self.sheet(FIGURE_OK))
        e = ln.reference_entries(d)[-1]
        self.assertEqual(e["figure"]["caption"], "two pointers closing in")
        self.assertIn("<svg", e["figure"]["svg"])
        self.assertNotIn("svg", e["body"])
        self.assertEqual(ln.validate_reference(self.sheet(FIGURE_OK)), [])

    def test_a_scripted_figure_is_refused(self):
        bad = FIGURE_OK.replace("<circle", "<script>x</script><circle")
        errs = ln.validate_reference(self.sheet(bad))
        self.assertTrue(any("script" in e for e in errs), errs)

    def test_an_unclosed_figure_is_a_problem(self):
        errs = ln.validate_reference(self.sheet(
            'figure:: cap\n<svg viewBox="0 0 1 1">\n'))
        self.assertTrue(any("never closed" in e for e in errs), errs)

    def test_a_second_figure_is_a_problem(self):
        errs = ln.validate_reference(self.sheet(FIGURE_OK + FIGURE_OK))
        self.assertTrue(any("second figure" in e for e in errs), errs)

    def test_an_exam_figure_spends_budget(self):
        with_fig = self.sheet(FIGURE_OK).replace(
            "kind:: definition\ntier:: full\nSome prose.",
            "kind:: definition\ntier:: exam\nSome prose.")
        d = ln.parse_reference(with_fig)
        plain = d
        base = sum(len(e["title"]) + len(e["body"]) + 2
                   for e in ln.reference_entries(plain, "exam"))
        self.assertEqual(ln.reference_size(d), base + ln.REF_FIGURE_COST)


class TestGeneralSheets(unittest.TestCase):
    """A topic that is not a course — the sheet lives in 04-Resources/,
    keyed by its filename, and rides the same loader and scan."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        res = self.vault / "04-Resources"
        res.mkdir(parents=True)
        (res / "dsa-reference.md").write_text(
            OK.replace("course: AA-210", "course: DSA"), encoding="utf-8")
        # A resource note sharing the name must stay a resource.
        (res / "old-notes-reference.md").write_text(
            "---\ntype: resource\ntags: [resource]\n---\n\n# Old notes\n",
            encoding="utf-8")
        self.open_split = lambda _v, rels: (set(), set(rels))

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_topic_loads_by_its_filename_key(self):
        d = ln.load_reference(self.vault, "DSA", split=self.open_split)
        self.assertIsNotNone(d)
        self.assertEqual(d["file"], "04-Resources/dsa-reference.md")

    def test_the_scan_lists_it_and_only_it(self):
        d = ln.scan_references(self.vault, split=self.open_split)
        self.assertEqual([s["course"] for s in d["sheets"]], ["DSA"])
        self.assertEqual(d["extras"], [])

    def test_an_academics_course_still_wins_the_name(self):
        """A course folder and a general sheet sharing a key: the course's own
        sheet is the one the key resolves — Academics is checked first."""
        course = self.vault / "02-Areas" / "Academics" / "DSA"
        course.mkdir(parents=True)
        (course / "dsa-reference.md").write_text(OK.replace(
            "course: AA-210", "course: DSA"), encoding="utf-8")
        d = ln.load_reference(self.vault, "DSA", split=self.open_split)
        self.assertEqual(d["file"], "02-Areas/Academics/DSA/dsa-reference.md")

    def test_sealing_withholds_it(self):
        d = ln.scan_references(self.vault,
                               split=lambda _v, rels: (set(rels), set()))
        self.assertEqual(d["sheets"], [])


class TestScan(unittest.TestCase):
    """`scan_references` — the RF slot's list. What is worth pinning: the
    two families stay split (a `type: reference` sheet summarises, any other
    `*-reference.md` at the course root lists as an extra), the summary is a
    summary rather than the sections, and sealing withholds each family the
    same fail-closed way as everything else."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        folder = self.vault / "02-Areas" / "Academics" / "AA-210"
        folder.mkdir(parents=True)
        (folder / "aa-210-reference.md").write_text(OK, encoding="utf-8")
        (folder / "imported-tables-reference.md").write_text(
            "---\ntype: resource\ncourse: AA-210\ntags: [resource]\n---\n\n"
            "# Imported tables\n\nbody\n", encoding="utf-8")
        # A second course with only an extra — it must still appear.
        other = self.vault / "02-Areas" / "Academics" / "CSE-999"
        other.mkdir(parents=True)
        (other / "old-notes-reference.md").write_text(
            "---\ntype: resource\ncourse: CSE-999\ntags: [resource]\n---\n\n"
            "no heading here\n", encoding="utf-8")
        self.open_split = lambda _v, rels: (set(), set(rels))

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_two_families_come_back_split(self):
        d = ln.scan_references(self.vault, split=self.open_split)
        self.assertEqual([s["course"] for s in d["sheets"]], ["AA-210"])
        self.assertEqual([e["course"] for e in d["extras"]],
                         ["AA-210", "CSE-999"])

    def test_the_sheet_row_is_a_summary_not_the_sections(self):
        d = ln.scan_references(self.vault, split=self.open_split)
        row = d["sheets"][0]
        self.assertEqual(row["sections"], 2)          # a count, not a list
        self.assertEqual(row["counts"], {"all": 3, "exam": 2})
        self.assertEqual(row["held"], 0)
        self.assertEqual(row["exam_budget"], ln.EXAM_BUDGET)
        self.assertNotIn("problems", row)

    def test_an_extra_names_itself_by_its_heading(self):
        d = ln.scan_references(self.vault, split=self.open_split)
        by_course = {e["course"]: e for e in d["extras"]}
        self.assertEqual(by_course["AA-210"]["title"], "Imported tables")
        # No H1 → the basename, made readable.
        self.assertEqual(by_course["CSE-999"]["title"], "old notes reference")

    def test_sealing_withholds_both_families(self):
        d = ln.scan_references(self.vault,
                               split=lambda _v, rels: (set(rels), set()))
        self.assertEqual(d, {"sheets": [], "extras": []})

    def test_the_default_split_fails_closed(self):
        """A vault the privacy module cannot answer for lists nothing —
        `load_reference`'s direction, kept."""
        d = ln.scan_references(self.vault)
        self.assertEqual(d, {"sheets": [], "extras": []})


class TestDispatch(unittest.TestCase):
    def test_validate_any_routes_by_the_note_s_own_type(self):
        """Running the module validator over a reference would report a dozen
        missing-segment complaints and bury the real one."""
        self.assertEqual(ln.validate_any(OK), [])
        self.assertTrue(ln.validate(OK), "the module validator should reject it")


if __name__ == "__main__":
    unittest.main()
