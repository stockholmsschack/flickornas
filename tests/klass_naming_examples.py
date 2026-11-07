"""Refused group examples used by client and web tests."""
from flickornas_standings.klass_naming import KlassNameReason, KlassNamingProblem


def bad_names():
    return (
        KlassNamingProblem(100, 'Test tournament', 101, 'Klass Minior',
                           KlassNameReason.AMBIGUOUS_KLASS, 'keep the intended klass'),
        KlassNamingProblem(100, 'Test tournament', 102, 'Minior Nybörjare <script>',
                           KlassNameReason.SEVERAL_KLASSES, 'keep one description'),
    )

