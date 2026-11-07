from pathlib import Path

import pytest

from flickornas_standings.klass_naming import KlassNameReason, KlassNameRefused, read_klass
from tests.legacy_klass_reader import legacy_extract_klass

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / '_spec-requirements/flickornas-klass-naming-spec.md'
ACCEPTED_KLASSES = {'a', 'b', 'ab', 'c', 'd', 'e', 'f', 'g', 'h', 'z', 'y', 'r', 'q', 'p', 'skipped'}


def table_rows(path, columns):
    for line in path.read_text().splitlines():
        if line.startswith('|'):
            row = [cell.strip().strip('`') for cell in line.strip('|').split('|')]
            if len(row) == columns:
                yield row


DOCUMENTED_NAMES = [
    row for row in table_rows(ROOT / 'KLASS_NAMING.md', 2) if row[1] in ACCEPTED_KLASSES
]
DOCUMENTED_REFUSALS = [
    row for row in table_rows(ROOT / 'KLASS_NAMING.md', 4) if row[2] in set(KlassNameReason)
]
COMPATIBILITY_ROWS = [row for row in table_rows(SPEC, 3) if row[0].isdecimal()]
OLD_MISTAKES = [row for row in table_rows(SPEC, 4) if row[0] not in {'Group name', '---'}]


def assert_refused(name, code):
    with pytest.raises(KlassNameRefused) as caught:
        read_klass(name)
    assert caught.value.reason == code
    assert caught.value.group_name == name
    assert caught.value.detail


def test_documents_have_the_expected_rows():
    assert len(DOCUMENTED_NAMES) > 30
    assert {code for _, _, code, _ in DOCUMENTED_REFUSALS} == set(KlassNameReason)
    assert len(COMPATIBILITY_ROWS) == 34
    assert len(OLD_MISTAKES) == 25


@pytest.mark.parametrize(('name', 'expected'), DOCUMENTED_NAMES)
def test_documented_names(name, expected):
    assert read_klass(name) == (None if expected == 'skipped' else expected)


@pytest.mark.parametrize(('name', 'explanation', 'code', 'replacement'), DOCUMENTED_REFUSALS)
def test_documented_refusals_and_replacements(name, explanation, code, replacement):
    assert_refused(name, code)
    assert read_klass(replacement) is not None


@pytest.mark.parametrize(('tournament', 'name', 'klass'), COMPATIBILITY_ROWS)
def test_real_2026_compatibility_table(tournament, name, klass):
    assert read_klass(name) == klass


@pytest.mark.parametrize(('name', 'today', 'required', 'explanation'), OLD_MISTAKES)
def test_old_mistakes_and_required_outcomes(name, today, required, explanation):
    assert legacy_extract_klass(name) == (None if today == 'skipped' else today)
    if required.startswith('refuse '):
        assert_refused(name, required.removeprefix('refuse ').strip('`'))
    else:
        assert read_klass(name) == (None if required.startswith('skipped') else required)


@pytest.mark.parametrize(('name', 'klass'), [
    ('Klass E Nybörjare', 'z'), ('Allmänna Klass B', 'y'),
    ('Öppen grupp', 'y'), ('Öppen Klass för alla', 'y'), ('Juniorklass A', 'p'),
])
def test_already_correct_names(name, klass):
    assert legacy_extract_klass(name) == klass
    assert read_klass(name) == klass


@pytest.mark.parametrize(
    'name', ['Minior', 'minior', 'MINIOR', 'Miniorklass A', 'Miniorgrupp B', 'Minior A', 'MINIOR KLASS A'],
)
def test_minior_keyword(name):
    assert read_klass(name) == 'r'


@pytest.mark.parametrize('name', ['Klass Minior', 'Minior grupp B', 'Klass A Minior', 'Grupp Minior'])
def test_minior_beside_another_klass_is_ambiguous(name):
    assert_refused(name, 'ambiguous_klass')


@pytest.mark.parametrize('word', ['Nybörjare', 'Allmän', 'Öppen', 'Junior', 'Kadett'])
def test_minior_with_a_description_names_several_klasses(word):
    assert_refused('Klass A Minior ' + word, 'several_klasses')


def test_minior_precedence():
    assert_refused('Ickeminior', 'no_klass')
    assert read_klass('Ickeminior Klass C') == 'c'
    assert read_klass('Minior Miniorer') == 'r'
    assert read_klass('Allmän Öppen') == 'y'
    assert read_klass('Minior Final Junior') is None


@pytest.mark.parametrize('name', ['Final', 'final', 'Finalen', 'finalen', 'Klass A - Final'])
def test_finals_are_skipped(name):
    assert read_klass(name) is None


@pytest.mark.parametrize('name', ['FINAL', 'Finaler', 'Semifinal'])
def test_finals_are_exact_whole_words(name):
    assert_refused(name, 'no_klass')
