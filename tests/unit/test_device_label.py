"""The device label shown for each signed-in session in Settings → Security."""

from __future__ import annotations

import pytest

from finance_core.auth.devices import device_label

CHROME = "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0"


@pytest.mark.parametrize(
    ("user_agent", "label"),
    [
        (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) {CHROME} Safari/537.36",
            "Chrome on Windows",
        ),
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
            "Safari on iPhone",
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/18.0 Safari/605.1.15",
            "Safari on macOS",
        ),
        (
            "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
            "Firefox on Linux",
        ),
        (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) {CHROME} Safari/537.36 Edg/130.0.0.0",
            "Edge on Windows",
        ),
        (
            f"Mozilla/5.0 (Linux; Android 10; K) {CHROME} Mobile Safari/537.36",
            "Chrome on Android",
        ),
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) CriOS/130.0.6723.90 Mobile/15E148 Safari/604.1",
            "Chrome on iPhone",
        ),
        (
            "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) FxiOS/131.0 Mobile/15E148 Safari/605.1.15",
            "Firefox on iPad",
        ),
        (
            "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) "
            "SamsungBrowser/26.0 Chrome/122.0.0.0 Mobile Safari/537.36",
            "Samsung Internet on Android",
        ),
        (
            f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) {CHROME} Safari/537.36 OPR/115.0",
            "Opera on macOS",
        ),
        (
            f"Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) {CHROME} Safari/537.36",
            "Chrome on ChromeOS",
        ),
    ],
)
def test_common_browsers_are_named_with_their_operating_system(user_agent: str, label: str) -> None:
    assert device_label(user_agent) == label


@pytest.mark.parametrize(
    "user_agent", ["curl/8.4.0", "python-httpx/0.28.1", "PostmanRuntime/7.39.0", "okhttp/4.12.0"]
)
def test_programs_calling_the_api_are_api_clients(user_agent: str) -> None:
    assert device_label(user_agent) == "API client"


@pytest.mark.parametrize("user_agent", [None, "", "   ", "Mozilla/5.0 (compatible)"])
def test_missing_or_unrecognised_user_agents_are_an_unknown_device(user_agent: str | None) -> None:
    assert device_label(user_agent) == "Unknown device"


def test_a_partly_recognised_browser_keeps_what_is_known() -> None:
    assert device_label("Mozilla/5.0 (Windows NT 10.0) NewBrowser/1.0") == "Browser on Windows"
    assert device_label("Mozilla/5.0 (compatible) Firefox/131.0") == "Firefox"
