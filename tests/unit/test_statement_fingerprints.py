"""Row fingerprints: what makes a re-import skip rows it already saved."""

from __future__ import annotations

import uuid
from datetime import date

from finance_core.imports.fingerprint import assign_fingerprints, row_fingerprint
from finance_core.imports.rows import ParsedRow

ACCOUNT = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _row(description: str = "Swiggy", amount_minor: int = 45000, day: int = 1) -> ParsedRow:
    return ParsedRow(
        position=1, raw_cells=[], occurred_on=date(2026, 10, day), amount_minor=amount_minor,
        direction="out", description=description, reference=None, problem=None,
    )  # fmt: skip


def test_the_same_file_read_twice_gives_the_same_fingerprints() -> None:
    file_rows = [_row(), _row("Uber", 21800, 2)]
    assert assign_fingerprints(ACCOUNT, file_rows) == assign_fingerprints(ACCOUNT, file_rows)


def test_two_identical_payments_in_one_file_stay_distinct() -> None:
    first, second = assign_fingerprints(ACCOUNT, [_row(), _row()])
    assert first != second


def test_the_occurrence_number_is_stable_when_other_rows_come_between() -> None:
    alone = assign_fingerprints(ACCOUNT, [_row(), _row()])
    interleaved = assign_fingerprints(ACCOUNT, [_row(), _row("Uber", 100, 3), _row()])
    assert interleaved[0] == alone[0]
    assert interleaved[2] == alone[1]


def test_spacing_and_case_in_the_description_do_not_change_the_fingerprint() -> None:
    assert assign_fingerprints(ACCOUNT, [_row("SWIGGY  Order")]) == assign_fingerprints(
        ACCOUNT, [_row("swiggy order")]
    )


def test_a_different_account_amount_or_direction_gives_a_different_fingerprint() -> None:
    base = row_fingerprint(ACCOUNT, date(2026, 10, 1), 45000, "out", "Swiggy", 1)
    other_account = uuid.UUID("22222222-2222-4222-8222-222222222222")
    assert base != row_fingerprint(other_account, date(2026, 10, 1), 45000, "out", "Swiggy", 1)
    assert base != row_fingerprint(ACCOUNT, date(2026, 10, 1), 45001, "out", "Swiggy", 1)
    assert base != row_fingerprint(ACCOUNT, date(2026, 10, 1), 45000, "in", "Swiggy", 1)


def test_a_row_that_could_not_be_read_has_no_fingerprint() -> None:
    broken = ParsedRow(
        position=1, raw_cells=[], occurred_on=None, amount_minor=None, direction=None,
        description=None, reference=None, problem="No date",
    )  # fmt: skip
    assert assign_fingerprints(ACCOUNT, [broken, _row()])[0] is None


def test_a_fingerprint_fits_the_idempotency_key_column() -> None:
    [key] = assign_fingerprints(ACCOUNT, [_row()])
    assert key is not None
    assert len(key) <= 128
