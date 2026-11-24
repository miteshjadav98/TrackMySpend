"""Merchant extraction examples shaped like common Indian bank exports."""

from __future__ import annotations

import pytest

from finance_core.imports.merchant import extract_merchant


@pytest.mark.parametrize(
    ("narration", "expected"),
    [
        ("UPI/402112345678/SWIGGY/swiggy@icici/Payment", "SWIGGY"),
        ("UPI/P2M/627412345678/DR LAL PATHLABS/YESB", "DR LAL PATHLABS"),
        ("NEFT/INWARD/UTR NO: HDFC261027123456/ACME CORP/PAYROLL", "ACME CORP"),
        ("IMPS/P2A/627412345678/QUICK CABS/HDFC0000001", "QUICK CABS"),
        ("IMPS-CR-REF NO 00002745-NORTHWIND SERVICES", "NORTHWIND SERVICES"),
        ("RTGS CR-UTR NO: SBINR12026101512345678-TATA POWER-MUMBAI", "TATA POWER"),
        ("POS 4291XXXXXXXX1234 PUR BIGBASKET", "BIGBASKET"),
        ("ATM/WDL/627412345678/XXXX1234/NFS/SBI MG ROAD", "SBI MG ROAD"),
        ("ATM CASH WITHDRAWAL AT SBI MG ROAD 627412345678", "SBI MG ROAD"),
        ("VISA/XXXX/1234/TATA 1MG/BANGALORE", "TATA 1MG"),
        ("DC PUR 4291XXXXXXXX1234 APOLLO PHARMACY", "APOLLO PHARMACY"),
        ("D-MART HINJEWADI", "D-MART HINJEWADI"),
        ("UPI/P2M/402112345678/VPA/onlyhandle@icici/PAYMENT", None),
        ("RTGS/UTR/UTIBR12026101512345678/₹1,250.75", None),
        ("ATM/WDL/NFS/XXXX1234/627412345678", None),
    ],
)
def test_bank_narrations_keep_the_name_and_drop_the_routing_fields(
    narration: str, expected: str | None
) -> None:
    assert extract_merchant(narration) == expected
