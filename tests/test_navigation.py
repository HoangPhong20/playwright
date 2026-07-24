from datetime import date
from urllib.parse import parse_qs, urlsplit

from agoda_crawler.navigation import (
    _build_city_search_urls,
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
