import pytest

from echohub.formatting import bar, compact, human_bytes, human_kb, relative_time


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "-"),
        (-5, "0 B"),
        (999, "999 B"),
        (1_500, "1.5 KB"),
        (17_947_333, "17.9 MB"),
        (99_940_000, "99.9 MB"),
        (123_400_000, "123 MB"),
        (2_500_000_000, "2.5 GB"),
    ],
)
def test_human_bytes_keeps_a_decimal_below_100(
    value: float | None, expected: str
) -> None:
    assert human_bytes(value) == expected


def test_human_kb_uses_the_same_units() -> None:
    assert human_kb(17_947.333) == "17.9 MB"
    assert human_kb(None) == "-"


def test_compact_and_bar() -> None:
    assert compact(1_830) == "1.8K"
    assert compact(42) == "42"
    assert bar(0.5, 4) == "██░░"
    assert bar(2.0, 2) == "██"


def test_relative_time_handles_bad_input() -> None:
    assert relative_time("") == "unknown"
    assert relative_time("not a date") == "not a date"
