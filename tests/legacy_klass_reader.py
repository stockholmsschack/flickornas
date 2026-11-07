"""Frozen pre-fix parser, used only to demonstrate regression cases."""
import re

def legacy_extract_klass(group_name: str) -> str | None:
    """Return the Flickornas standings class encoded in a group name."""
    lowered = group_name.lower()
    special_names = (
        ("nybörjar", "z"),
        ("allmän", "y"),
        ("öppen", "y"),
        ("minior", "r"),
        ("kadet", "q"),
        ("junior", "p"),
    )
    for marker, klass in special_names:
        if marker in lowered:
            return klass

    label = "grupp" if re.search(r"grupp\s+", lowered) else "klass"
    if label == "klass" and label not in lowered:
        return None
    matches = re.findall(rf"{label}\s+([A-Za-z]+)", group_name, re.IGNORECASE)
    result = "".join(matches)
    separated = re.search(
        rf"{label}\s+([A-Za-z])[/\-,&+ ]+([A-Za-z])",
        group_name,
        re.IGNORECASE,
    )
    if separated and len(result) == 1:
        result = "".join(separated.groups())
    return result.lower() if result else None
