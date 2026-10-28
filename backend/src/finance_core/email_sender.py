"""Outgoing email: the `EmailSender` interface and the console sender that stands in for one.

No email provider has been chosen yet, so the only sender writes each email to the log. The
app takes its sender through `create_app`, so tests can capture what would have been sent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from finance_core.config import Environment

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """A plain-text email to one recipient."""

    to: str
    subject: str
    text: str


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None:
        """Deliver the message, or say in the log why it was not delivered."""
        ...


class ConsoleEmailSender:
    """Prints emails to the API log instead of sending them.

    Outside production the whole email is logged, links included, so the reset flow can be
    tried locally. In production nothing is sent and the body is never logged: a reset link
    in the log would let anyone who can read the logs take over the account.
    """

    def __init__(self, environment: Environment) -> None:
        self._environment = environment

    async def send(self, message: EmailMessage) -> None:
        if self._environment == "production":
            logger.warning(
                "email not sent: no email provider is configured",
                extra={"subject": message.subject},
            )
            return
        logger.info(
            "email printed here instead of sent (no email provider)\nTo: %s\nSubject: %s\n\n%s",
            message.to,
            message.subject,
            message.text,
        )
