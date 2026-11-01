"""Turns a session's User-Agent header into a short device label, such as "Chrome on Windows".

The label helps a user recognise their own devices in Settings → Security. It is a best
guess from well-known tokens, never used for any security decision, so a small table beats
a user-agent parsing dependency.
"""

from __future__ import annotations

API_CLIENT = "API client"
UNKNOWN_DEVICE = "Unknown device"

# Order matters: Edge, Opera and Samsung Internet also say "Chrome", and Chrome also says
# "Safari", so the more specific browsers are checked first.
_BROWSERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Edge", ("Edg/", "EdgA/", "EdgiOS/", "Edge/")),
    ("Opera", ("OPR/", "OPT/")),
    ("Samsung Internet", ("SamsungBrowser/",)),
    ("Firefox", ("Firefox/", "FxiOS/")),
    ("Chrome", ("Chrome/", "CriOS/")),
    ("Safari", ("Safari/",)),
)

# Order matters: Android also says "Linux", and iPhones and iPads say "like Mac OS X".
_SYSTEMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("iPhone", ("iPhone",)),
    ("iPad", ("iPad",)),
    ("Android", ("Android",)),
    ("Windows", ("Windows",)),
    ("ChromeOS", ("CrOS",)),
    ("macOS", ("Macintosh",)),
    ("Linux", ("Linux",)),
)


def _first_named(user_agent: str, table: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    for name, tokens in table:
        if any(token in user_agent for token in tokens):
            return name
    return None


def device_label(user_agent: str | None) -> str:
    """A short, human label for the browser and operating system in a User-Agent header."""
    agent = (user_agent or "").strip()
    if not agent:
        return UNKNOWN_DEVICE
    # Every browser's User-Agent starts with "Mozilla/"; anything else is a program, such as
    # curl or a script, calling the API.
    if not agent.startswith("Mozilla/"):
        return API_CLIENT
    browser = _first_named(agent, _BROWSERS)
    system = _first_named(agent, _SYSTEMS)
    if browser and system:
        return f"{browser} on {system}"
    if system:
        return f"Browser on {system}"
    return browser or UNKNOWN_DEVICE
