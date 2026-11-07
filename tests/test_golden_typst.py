from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from compare_typst import TypstMismatch, compare_typst


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ARTIFACTS = PROJECT_ROOT / "reference-artifacts"
GOLDEN_TYPST = REFERENCE_ARTIFACTS / "2026-standings-golden.typ"
ACCEPTANCE_RECORD = REFERENCE_ARTIFACTS / "2026-golden-acceptance.json"


class TypstComparisonTests(unittest.TestCase):
    def test_identical_typst_passes(self):
        compare_typst(GOLDEN_TYPST, GOLDEN_TYPST)

    def test_content_change_fails(self):
        changed = GOLDEN_TYPST.read_text().replace(
            "Flickornas Ställning",
            "Ändrad ställning",
            1,
        )

        with tempfile.TemporaryDirectory() as directory:
            changed_path = Path(directory) / "content-change.typ"
            changed_path.write_text(changed)
            with self.assertRaisesRegex(TypstMismatch, "generated Typst differs"):
                compare_typst(GOLDEN_TYPST, changed_path)

    def test_layout_change_fails(self):
        changed = GOLDEN_TYPST.read_text().replace(
            'font: "Roboto"',
            'font: "Fira Sans Condensed"',
            1,
        )

        with tempfile.TemporaryDirectory() as directory:
            changed_path = Path(directory) / "layout-change.typ"
            changed_path.write_text(changed)
            with self.assertRaisesRegex(TypstMismatch, "generated Typst differs"):
                compare_typst(GOLDEN_TYPST, changed_path)


class GoldenAcceptanceTests(unittest.TestCase):
    def test_acceptance_record_identifies_and_hashes_reviewed_artifacts(self):
        acceptance = json.loads(ACCEPTANCE_RECORD.read_text())

        self.assertEqual(acceptance["status"], "accepted")
        self.assertTrue(acceptance["accepted_by"])
        self.assertTrue(acceptance["accepted_at"])

        for artifact_key in ("input_archive", "golden_typst", "reviewed_pdf"):
            artifact = acceptance[artifact_key]
            artifact_path = REFERENCE_ARTIFACTS / artifact["path"]
            digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            self.assertEqual(digest, artifact["sha256"])


if __name__ == "__main__":
    unittest.main()
