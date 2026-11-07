from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REMOVED_SCAFFOLDING = (
    "MemoryOptimizedExcelExporter",
    "memory_profiler",
    "devtools",
    "create_or_clear_directory",
)
CHECKED_PATHS = [
    *PROJECT_ROOT.glob("*.py"),
    *sorted((PROJECT_ROOT / "flickornas_standings").rglob("*.py")),
    PROJECT_ROOT / "pyproject.toml",
    PROJECT_ROOT / "uv.lock",
]


@pytest.mark.parametrize(
    "path", CHECKED_PATHS, ids=lambda path: str(path.relative_to(PROJECT_ROOT))
)
@pytest.mark.parametrize("removed_name", REMOVED_SCAFFOLDING)
def test_obsolete_scaffolding_is_absent_from_code_and_dependencies(path, removed_name):
    assert removed_name not in path.read_text()
