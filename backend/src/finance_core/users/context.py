from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from finance_core.clock import Clock, today_in


@dataclass(frozen=True, slots=True)
class UserContext:
    """Who is acting and how their input should be interpreted.

    Built from the authenticated session plus the stored profile, never from request
    bodies or model output, so identity cannot be spoofed by a prompt.
    """

    user_id: uuid.UUID
    base_currency: str
    timezone: str
    locale: str

    def today(self, clock: Clock) -> date:
        return today_in(clock, self.timezone)
