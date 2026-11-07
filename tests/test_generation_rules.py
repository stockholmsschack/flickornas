from flickornas_standings.generation_rules import youngest_group_start_year


def test_2026_youngest_group_uses_effective_year():
    assert youngest_group_start_year(2026) == 2017
