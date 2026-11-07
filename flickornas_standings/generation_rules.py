from .klass_naming import read_klass


def youngest_group_start_year(effective_year: int) -> int:
    """Return the first birth year included in the youngest group."""
    if isinstance(effective_year, bool) or not isinstance(effective_year, int):
        raise ValueError("effective year must be an integer")
    return effective_year - 9


def extract_klass(group_name: str) -> str | None:
    """Read a group name using the documented strict naming rules."""
    return read_klass(group_name)
