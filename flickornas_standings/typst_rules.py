"""Persistence for the Typst rules page used by generated PDFs."""

from __future__ import annotations

from pathlib import Path

from .atomic_write import atomic_replace_bytes


BUILT_IN_RULES_PATH = Path(__file__).resolve().parent.parent / "typst" / "rules.typ"
CUSTOM_RULES_PATH = Path("typst") / "rules.typ"
MAX_RULES_FILE_BYTES = 1_000_000


class RulesFileValidationError(ValueError):
    """Raised when an uploaded rules file cannot be used."""


def effective_rules_path(
    state_directory: Path,
    fallback: Path = BUILT_IN_RULES_PATH,
) -> Path:
    """Return the uploaded rules file or the supplied built-in fallback."""
    custom_path = custom_rules_path(state_directory)
    return custom_path if custom_path.is_file() else Path(fallback)


def custom_rules_path(state_directory: Path) -> Path:
    """Return the path reserved for an uploaded rules file."""
    return Path(state_directory) / CUSTOM_RULES_PATH


def save_rules_file(state_directory: Path, content: bytes) -> Path:
    """Validate and atomically replace the active custom rules file."""
    if not content:
        raise RulesFileValidationError("the rules file is empty")
    if len(content) > MAX_RULES_FILE_BYTES:
        raise RulesFileValidationError("the rules file is too large")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RulesFileValidationError(
            "the rules file must use UTF-8 encoding"
        ) from error

    destination = custom_rules_path(state_directory)
    atomic_replace_bytes(destination, content)
    return destination


def restore_built_in_rules(state_directory: Path) -> bool:
    """Remove the uploaded override and report whether one existed."""
    custom_path = custom_rules_path(state_directory)
    existed = custom_path.is_file()
    custom_path.unlink(missing_ok=True)
    return existed
