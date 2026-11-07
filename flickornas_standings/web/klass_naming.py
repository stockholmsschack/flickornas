"""Browser problem serialization for group naming refusals."""
from collections.abc import Iterable

from ..klass_naming import KlassNamingProblem


def klass_naming_problems(problems: Iterable[KlassNamingProblem]) -> list[dict]:
    return [
        {
            "field": "tournaments",
            "message_key": f"errors.klass_naming.{problem.reason}",
            "parameters": {
                "tournament_id": problem.tournament_id,
                "tournament_name": problem.tournament_name,
                "group_id": problem.group_id,
                "group_name": problem.group_name,
            },
        }
        for problem in problems
    ]
