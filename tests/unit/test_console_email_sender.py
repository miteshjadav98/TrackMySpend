"""The console sender: prints emails to the log until an email provider is chosen."""

from __future__ import annotations

import logging

import pytest

from finance_core.email_sender import ConsoleEmailSender, EmailMessage

LINK = "http://localhost:3000/reset-password#token=abc123"
MESSAGE = EmailMessage(
    to="asha@example.com",
    subject="Reset your MoneyMoney password",
    text=f"To choose a new password, open this link within 30 minutes:\n{LINK}",
)


async def test_outside_production_the_whole_email_is_logged_link_included(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="finance_core.email_sender"):
        await ConsoleEmailSender("local").send(MESSAGE)

    [record] = caplog.records
    assert record.levelno == logging.INFO
    assert LINK in record.getMessage()
    assert "asha@example.com" in record.getMessage()


async def test_in_production_nothing_is_sent_and_the_link_never_reaches_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="finance_core.email_sender"):
        await ConsoleEmailSender("production").send(MESSAGE)

    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert "abc123" not in caplog.text
    assert "abc123" not in repr(vars(record))
