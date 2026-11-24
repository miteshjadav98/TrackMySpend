"""The exact merchant groups shared by report totals and transaction drill-down.

Report names use Unicode case folding, independently of merchant-rule normalization.
Retaining the original spellings makes SQL filtering exact without relying on a database
collation or treating a similarly named merchant as a match.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReportMerchantGroup:
    """One named merchant or the remainder, including its original stored spellings."""

    key: str
    name: str
    total: int = 0
    count: int = 0
    aliases: list[str | None] = field(default_factory=list)
    is_other: bool = False


def report_merchant_key(name: str | None) -> str:
    """Exactly the normalization used by reports, including non-ASCII merchant names."""
    return name.strip().casefold() if name else ""


def report_merchant_groups(rows: list[tuple[str | None, int, int]]) -> list[ReportMerchantGroup]:
    """Rank the top ten named merchants and combine every remaining or unnamed row."""
    named: dict[str, ReportMerchantGroup] = {}
    other = ReportMerchantGroup(key="other", name="Other merchants", is_other=True)
    for merchant, total, count in rows:
        key = report_merchant_key(merchant)
        if key:
            name = (merchant or "").strip()
            group = named.setdefault(key, ReportMerchantGroup(key=key, name=name))
            group.name = min(group.name, name, key=lambda value: (value.casefold(), value))
        else:
            group = other
        group.total += total
        group.count += count
        group.aliases.append(merchant)

    ranked = sorted(named.values(), key=lambda group: (-group.total, group.name.casefold()))
    for group in ranked[10:]:
        other.total += group.total
        other.count += group.count
        other.aliases.extend(group.aliases)
    return ranked[:10] + ([other] if other.count else [])
