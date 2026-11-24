"""The model gets classification clues without transaction numbers or payment handles."""

from finance_core.imports.categorise import category_text


def test_redaction_keeps_upi_purpose_and_removes_amounts_and_handles() -> None:
    text = category_text(
        "Acme", "UPI/627412345678/ACME/acme@icici/FOOD/INR500/₹1234.50CR/105.75 DR/ICIC0000385"
    )

    assert text == "Acme UPI ACME FOOD"
