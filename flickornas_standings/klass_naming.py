"""Strict group-name parsing shared by client validation and organiser help."""

import re
from dataclasses import dataclass
from enum import StrEnum

KLASS_KEYWORDS = ('Klass', 'klass', 'Grupp', 'grupp')
MERGED_KLASS = 'AB'

_LETTER_OR_DIGIT = r'[^\W_]'
_LETTER = r'[^\W\d_]'

# The keyword as a word of its own, in any casing; "Klassisk" and "Nybörjargrupp" are not keywords.
_KEYWORD = re.compile(rf'(?<!{_LETTER})(?:klass|grupp)(?!{_LETTER})', re.IGNORECASE)

# Match one or two capital letters A–H after the keyword. Pairs may be adjacent
# or joined by / - + & , or a space. The final lookahead rejects a third letter.
_SEPARATOR = r'\s*[/\-+&,]?\s*'
_KLASS_AFTER_KEYWORD = re.compile(
    rf'\s+(?P<klass>[A-H]{{2}}|[A-H](?:{_SEPARATOR}[A-H])?)'
    rf'(?!{_LETTER_OR_DIGIT})'
    rf'(?!{_SEPARATOR}[A-H](?!{_LETTER_OR_DIGIT}))'
)


class KlassNameReason(StrEnum):
    """Stable reason codes for group-name validation errors."""

    NO_KLASS = 'no_klass'
    KEYWORD_SPELLING = 'keyword_spelling'
    SEVERAL_KLASSES = 'several_klasses'
    UNREADABLE_KLASS = 'unreadable_klass'
    UNKNOWN_MERGE = 'unknown_merge'
    AMBIGUOUS_KLASS = 'ambiguous_klass'


class KlassNameRefused(ValueError):
    """A group name that does not follow `KLASS_NAMING.md`."""

    def __init__(self, group_name: str, reason: KlassNameReason, detail: str) -> None:
        self.group_name = group_name
        self.reason = reason
        self.detail = detail
        super().__init__(f"group name {group_name!r}: {detail}")


@dataclass(frozen=True)
class KlassNamingProblem:
    """A tournament group whose name must be corrected at source."""

    tournament_id: int
    tournament_name: str
    group_id: int
    group_name: str
    reason: KlassNameReason
    detail: str

    def __str__(self) -> str:
        return (f"{self.tournament_name} ({self.tournament_id}), group {self.group_name!r} "
                f"(id {self.group_id}): {self.detail}")


def _read_letter_klass(group_name: str) -> str:
    """Return the declared klass (`a` through `h`, or `ab`).

    Raise `KlassNameRefused` for formats outside `KLASS_NAMING.md`.
    """
    keywords = list(_KEYWORD.finditer(group_name))
    if not keywords:
        raise KlassNameRefused(group_name, KlassNameReason.NO_KLASS,
                               "it has no 'Klass' or 'Grupp' followed by a klass letter")
    if len(keywords) > 1:
        raise KlassNameRefused(group_name, KlassNameReason.SEVERAL_KLASSES,
                               f"it names {len(keywords)} klasses; a group name declares exactly one")

    keyword = keywords[0]
    if keyword.group() not in KLASS_KEYWORDS:
        raise KlassNameRefused(group_name, KlassNameReason.KEYWORD_SPELLING,
                               f"{keyword.group()!r} is not an accepted spelling; write 'Klass'")

    klass = _KLASS_AFTER_KEYWORD.match(group_name, keyword.end())
    if klass is None:
        raise KlassNameRefused(group_name, KlassNameReason.UNREADABLE_KLASS,
                               f"'{keyword.group()}' must be followed by a space and one capital "
                               f"klass letter, A to H, standing on its own")

    letters = re.sub(r'[^A-H]', '', klass['klass'])
    if len(letters) == 2 and letters != MERGED_KLASS:
        raise KlassNameRefused(group_name, KlassNameReason.UNKNOWN_MERGE,
                               f"{klass['klass']!r} is not a klass; the only merged klass is A and B, "
                               f"written in that order")
    return letters.lower()



_FINALS = re.compile(r"\b(?:Final|final|Finalen|finalen)\b")
_DESCRIPTION_PATTERNS = (
    (re.compile(r"\bnybörjar", re.IGNORECASE), "z"),
    (re.compile(r"\b(?:allmän|öppen\b|öppna\b)", re.IGNORECASE), "y"),
    (re.compile(r"\bminior", re.IGNORECASE), "r"),
    (re.compile(r"\bkadet", re.IGNORECASE), "q"),
    (re.compile(r"\bjunior", re.IGNORECASE), "p"),
)


def read_klass(group_name: str) -> str | None:
    """Return the klass, return None for finals, or raise `KlassNameRefused`.

    Finals skip all other checks. Multiple description klasses are rejected first.
    Minior, Kadett and Junior conflict with accepted spellings of `Klass` or
    `Grupp`; other keyword casing leaves the description klass unchanged.
    """
    if _FINALS.search(group_name):
        return None
    descriptions = {
        klass for pattern, klass in _DESCRIPTION_PATTERNS
        if pattern.search(group_name)
    }
    if len(descriptions) > 1:
        raise KlassNameRefused(
            group_name, KlassNameReason.SEVERAL_KLASSES,
            "it names several description klasses; keep only the intended one",
        )
    if descriptions:
        klass = descriptions.pop()
        if klass in {"r", "q", "p"} and any(
            match.group() in KLASS_KEYWORDS
            for match in _KEYWORD.finditer(group_name)
        ):
            raise KlassNameRefused(
                group_name, KlassNameReason.AMBIGUOUS_KLASS,
                "an age description clashes with 'Klass' or 'Grupp'; keep either "
                "the age description alone or the intended letter phrase",
            )
        return klass
    return _read_letter_klass(group_name)
