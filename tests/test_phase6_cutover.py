from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_ENTRY_POINTS = (
    "flickorna_step_01_fetch_info.py",
    "flickorna_step_02_allocate_collate.py",
)
OPERATOR_DOCUMENTS = (
    PROJECT_ROOT / "usage.md",
    PROJECT_ROOT / "reference-artifacts" / "README.md",
)


@pytest.mark.parametrize("filename", LEGACY_ENTRY_POINTS)
def test_legacy_entry_points_are_absent(filename):
    assert not (PROJECT_ROOT / filename).exists()


@pytest.mark.parametrize("document", OPERATOR_DOCUMENTS, ids=lambda path: path.name)
@pytest.mark.parametrize("filename", LEGACY_ENTRY_POINTS)
def test_operator_docs_do_not_invoke_legacy_entry_points(document, filename):
    assert filename not in document.read_text(encoding="utf-8")
