from datetime import date
from urllib.parse import parse_qs, urlsplit

from agoda_crawler.navigation import _build_city_search_urls
from agoda_crawler.navigation.urls import search_page_urls
from agoda_crawler.navigation import search as navigation_search


class _HtmlPage:
    def __init__(self, html: str) -> None:
        self.html = html

    def content(self) -> str:
        return self.html


def test_is_activities_shell_ignores_cdn_reference_on_hotel_page() -> None:
    page = _HtmlPage(
        '<html><head><script src="https://cdn-activities.agoda.com/app.js"></script>'
        '</head><body><button aria-selected="true">Hotels</button></body></html>'
    )

    assert not navigation_search._is_activities_shell(page)


def test_is_activities_shell_detects_activities_web_app_marker() -> None:
    page = _HtmlPage('<script type="application/json">{"appName" : "activities-web"}</script>')

    assert navigation_search._is_activities_shell(page)


def test_build_city_search_urls_adds_dates_destination_and_rich_params() -> None:
    urls = _build_city_search_urls(
        "https://www.agoda.com/vi-vn/search?city=17190&currencyCode=USD",
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
    assert query["currencyCode"] == ["VND"]


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
    assert all(parse_qs(urlsplit(url).query)["currencyCode"] == ["VND"] for url in urls)


def test_search_page_urls_force_vnd_when_paginating() -> None:
    urls = search_page_urls(
        "https://www.agoda.com/search?city=17190&currencyCode=USD&page=1", 2
    )

    assert urls
    assert all(parse_qs(urlsplit(url).query)["currencyCode"] == ["VND"] for url in urls)


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


def test_pagination_never_constructs_a_page_url_when_controls_are_missing(monkeypatch) -> None:
    monkeypatch.setattr(navigation_search, "_click_next_page_control", lambda _page: False)
    monkeypatch.setattr(navigation_search, "_click_page_number_control", lambda _page, _number: False)
    monkeypatch.setattr(navigation_search, "_open_next_page_link", lambda _page, _number: False)

    assert navigation_search.go_to_results_page(object(), 3, prefer_next=True) is False
