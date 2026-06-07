from datetime import date
from urllib.parse import parse_qs, urlsplit

from agoda_crawler.navigation import (
    _build_city_search_urls,
    _with_landing_dates,
    _with_search_page,
)
from agoda_crawler.navigation import search as navigation_search


def test_build_city_search_urls_adds_dates_destination_and_rich_params() -> None:
    urls = _build_city_search_urls(
        "https://www.agoda.com/vi-vn/search?city=17190",
        destination="Vung Tau",
        check_in_date=date(2026, 6, 10),
        check_out_date=date(2026, 6, 11),
    )

    assert urls
    first = urls[0]
    query = parse_qs(urlsplit(first).query, keep_blank_values=True)
    assert query["city"] == ["17190"]
    assert query["checkIn"] == ["2026-06-10"]
    assert query["checkOut"] == ["2026-06-11"]
    assert query["los"] == ["1"]
    assert query["rooms"] == ["1"]
    assert query["adults"] == ["2"]
    assert query["children"] == ["0"]
    assert query["textToSearch"] == ["Vung Tau"]
    assert query["travellerType"] == ["1"]


def test_build_city_search_urls_includes_non_localized_and_en_us_fallbacks() -> None:
    urls = _build_city_search_urls(
        "https://www.agoda.com/vi-vn/search?city=17190",
        destination="Vung Tau",
        check_in_date=date(2026, 6, 10),
        check_out_date=date(2026, 6, 11),
    )

    paths = {urlsplit(url).path for url in urls}
    assert "/vi-vn/search" in paths
    assert "/search" in paths
    assert "/en-us/search" in paths


def test_with_landing_dates_adds_occupancy_and_los() -> None:
    url = _with_landing_dates(
        "https://www.agoda.com/vi-vn/city/vung-tau-vn.html?cid=-1",
        "2026-06-10",
        "2026-06-12",
    )

    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    assert query["cid"] == ["-1"]
    assert query["checkIn"] == ["2026-06-10"]
    assert query["checkOut"] == ["2026-06-12"]
    assert query["los"] == ["2"]
    assert query["rooms"] == ["1"]
    assert query["adults"] == ["2"]
    assert query["children"] == ["0"]


def test_with_landing_dates_keeps_custom_occupancy() -> None:
    url = _with_landing_dates(
        "https://www.agoda.com/vi-vn/city/vung-tau-vn.html?cid=-1",
        "2026-06-10",
        "2026-06-12",
        adults=3,
        rooms=2,
        children=1,
    )

    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    assert query["rooms"] == ["2"]
    assert query["adults"] == ["3"]
    assert query["children"] == ["1"]


def test_with_search_page_sets_page_on_search_url() -> None:
    url = _with_search_page(
        "https://www.agoda.com/vi-vn/search?city=17190&checkIn=2026-06-10",
        2,
    )

    assert url is not None
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    assert query["city"] == ["17190"]
    assert query["checkIn"] == ["2026-06-10"]
    assert query["page"] == ["2"]


def test_with_search_page_rejects_non_search_url() -> None:
    assert _with_search_page(
        "https://www.agoda.com/vi-vn/city/vung-tau-vn.html?city=17190",
        2,
    ) is None


def test_force_hotel_mode_continue_allows_missing_hotels_tab(monkeypatch, capsys) -> None:
    def missing_tab(_page):
        raise RuntimeError("Cannot find Hotels tab on Agoda homepage")

    monkeypatch.setattr(navigation_search, "_force_hotel_mode", missing_tab)

    navigation_search._force_hotel_mode_or_continue(object())

    assert "Hotels tab not found" in capsys.readouterr().out


def test_force_hotel_mode_continue_reraises_other_errors(monkeypatch) -> None:
    def wrong_shell(_page):
        raise RuntimeError("Activities shell is active after selecting hotel mode")

    monkeypatch.setattr(navigation_search, "_force_hotel_mode", wrong_shell)

    try:
        navigation_search._force_hotel_mode_or_continue(object())
    except RuntimeError as exc:
        assert "Activities shell" in str(exc)
    else:
        raise AssertionError("Expected non-tab hotel mode errors to propagate")


class _ResultsWaitLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class _ResultsWaitPage:
    def __init__(self) -> None:
        self.counts = {}
        self.wait_function_calls = []

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        return None

    def wait_for_function(self, expression: str, *, arg, timeout: int) -> None:
        self.wait_function_calls.append((arg, timeout))
        self.counts['[data-testid="property-card"]'] = 1

    def locator(self, selector: str) -> _ResultsWaitLocator:
        return _ResultsWaitLocator(self.counts.get(selector, 0))


def test_wait_for_results_ready_uses_wait_for_function() -> None:
    page = _ResultsWaitPage()

    selector = navigation_search._wait_for_results_ready(
        page,
        before_signature="old",
        timeout_ms=1_000,
        require_change=True,
    )

    assert selector == '[data-testid="property-card"]'
    assert page.wait_function_calls


class _PaginationFallbackPage:
    url = "https://www.agoda.com/vi-vn/search?page=1"


class _PaginationFallbackControl:
    def __init__(self) -> None:
        self.js_scroll_calls = 0
        self.click_calls = 0

    def count(self) -> int:
        return 1

    def is_visible(self, timeout: int) -> bool:
        return True

    def is_disabled(self, timeout: int) -> bool:
        return False

    def get_attribute(self, name: str, timeout: int):
        return None

    def scroll_into_view_if_needed(self, timeout: int) -> None:
        raise TimeoutError("scroll timed out")

    def evaluate(self, expression: str, timeout: int) -> None:
        self.js_scroll_calls += 1

    def click(self, timeout: int) -> None:
        self.click_calls += 1


def test_activate_pagination_control_uses_js_scroll_fallback(monkeypatch) -> None:
    control = _PaginationFallbackControl()
    monkeypatch.setattr(navigation_search, "_wait_for_results_ready", lambda *args, **kwargs: None)

    assert navigation_search._activate_pagination_control(_PaginationFallbackPage(), control) is True
    assert control.js_scroll_calls == 1
    assert control.click_calls == 1
