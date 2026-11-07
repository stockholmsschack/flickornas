from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REMOVED_RUNTIME_NAMES = (
    "SeasonConfiguration",
    "SeasonConfigurationError",
    "validate_season_configuration",
    "season_year",
)
SINGLE_CONFIGURATION_DOCUMENTS = (
    "PRODUCT_INTENT.md",
    "UI_POKA_YOKE.md",
    "README.md",
    "usage.md",
)
RUNTIME_FILES = sorted((PROJECT_ROOT / "flickornas_standings").rglob("*.py"))


@pytest.mark.parametrize(
    "path", RUNTIME_FILES, ids=lambda path: str(path.relative_to(PROJECT_ROOT))
)
@pytest.mark.parametrize("removed_name", REMOVED_RUNTIME_NAMES)
def test_season_shaped_runtime_names_are_absent(path, removed_name):
    assert removed_name not in path.read_text()


@pytest.mark.parametrize(
    "filename",
    ["flickorna_config.toml", "flickorna_config.py", "season_rules.py"],
)
def test_repository_local_configuration_is_removed(filename):
    assert not (PROJECT_ROOT / filename).exists()


@pytest.mark.parametrize("filename", SINGLE_CONFIGURATION_DOCUMENTS)
def test_supporting_documents_do_not_describe_a_season_model(filename):
    assert "season" not in (PROJECT_ROOT / filename).read_text().lower()


def test_season_lifecycle_diagram_is_removed():
    assert not (
        PROJECT_ROOT / "_diagrams" / "season-lifecycle-and-publication.mmd"
    ).exists()
