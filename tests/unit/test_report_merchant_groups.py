"""Grouping rules are identical for displayed totals and the rows behind a drill-down."""

from finance_core.merchants.report_groups import report_merchant_groups


def test_unicode_aliases_and_a_named_other_stay_distinct_from_the_remainder() -> None:
    groups = report_merchant_groups(
        [
            ("Straße", 100, 1),
            ("STRASSE", 200, 2),
            ("Other", 50, 1),
            (None, 25, 1),
            ("  ", 15, 1),
        ]
    )
    assert [(group.key, group.total, group.count, group.is_other) for group in groups] == [
        ("strasse", 300, 3, False),
        ("other", 50, 1, False),
        ("other", 40, 2, True),
    ]
    assert groups[0].aliases == ["Straße", "STRASSE"]
    assert groups[-1].aliases == [None, "  "]


def test_top_ten_and_remainder_preserve_every_alias_and_amount() -> None:
    rows = [(f"Merchant {index:02}", index, 1) for index in range(12)]
    groups = report_merchant_groups(rows)
    assert len(groups) == 11
    assert groups[-1].is_other
    assert groups[-1].total == 1
    assert set(groups[-1].aliases) == {"Merchant 00", "Merchant 01"}
    assert sum(group.total for group in groups) == sum(total for _, total, _ in rows)
    assert sum(group.count for group in groups) == 12
    assert report_merchant_groups([]) == []
