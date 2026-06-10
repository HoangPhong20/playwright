"""URL and text helpers for Agoda navigation."""
import re
import unicodedata
from datetime import date, datetime
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_agoda_destination(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.replace("\u0111", "d").replace("\u0110", "D")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def with_search_page(page_url: str, page_number: int) -> Optional[str]:
    urls = search_page_urls(page_url, page_number)
    return urls[0] if urls else None


def search_page_urls(page_url: str, page_number: int) -> list[str]:
    if page_number < 1:
        return []

    split = urlsplit(page_url)
    if not re.search(r"/search/?$", split.path, re.I):
        return []

    query = dict(parse_qsl(split.query, keep_blank_values=True))
    if "city" not in query:
        return []

    urls: list[str] = []
    for param_name in ("page", "pageNumber", "pageIndex"):
        candidate_query = dict(query)
        candidate_query[param_name] = str(page_number)
        urls.append(
            urlunsplit(
                (
                    split.scheme,
                    split.netloc,
                    split.path,
                    urlencode(candidate_query, doseq=True),
                    "",
                )
            )
        )
    return urls


def url_targets_page(url: str, page_number: int) -> bool:
    query = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    expected = str(page_number)
    return any(
        query.get(param_name) == expected
        for param_name in ("page", "pageNumber", "pageIndex")
    )


def search_url_label(url: str) -> str:
    split = urlsplit(url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    path_parts = [part for part in split.path.split("/") if part]
    locale = path_parts[0] if path_parts and re.match(r"^[a-z]{2}-[a-z]{2}$", path_parts[0], re.I) else "default"
    price_mode = "priced" if query.get("finalPriceView") == "1" else "basic"
    city = query.get("city", "?")
    currency = query.get("currencyCode")
    currency_text = f", {currency}" if currency else ""
    return f"{locale}, {price_mode}{currency_text}, city={city}"


def build_city_search_urls(
    search_url: str,
    destination: str,
    check_in_date: date,
    check_out_date: date,
    adults: int = 2,
    rooms: int = 1,
    children: int = 0,
) -> list[str]:
    urls: list[str] = []
    for base_url in city_search_url_bases(search_url):
        urls.append(
            with_search_dates(
                base_url,
                destination=destination,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                adults=adults,
                rooms=rooms,
                children=children,
                rich=True,
            )
        )
        urls.append(
            with_search_dates(
                base_url,
                destination=destination,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                adults=adults,
                rooms=rooms,
                children=children,
                rich=False,
            )
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        deduped.append(url)
        seen.add(url)
    return deduped


def city_search_url_bases(search_url: str) -> list[str]:
    split = urlsplit(search_url)
    bases: list[str] = []
    path = split.path
    if re.match(r"^/[a-z]{2}-[a-z]{2}/search$", path, flags=re.I):
        bases.append(urlunsplit((split.scheme, split.netloc, "/search", split.query, "")))
    bases.append(search_url)
    if re.match(r"^/[a-z]{2}-[a-z]{2}/search$", path, flags=re.I):
        if not path.lower().startswith("/en-us/"):
            bases.append(urlunsplit((split.scheme, split.netloc, "/en-us/search", split.query, "")))
    deduped: list[str] = []
    seen: set[str] = set()
    for base in bases:
        if base in seen:
            continue
        deduped.append(base)
        seen.add(base)
    return deduped


def with_search_dates(
    search_url: str,
    destination: str,
    check_in_date: date,
    check_out_date: date,
    adults: int = 2,
    rooms: int = 1,
    children: int = 0,
    rich: bool = False,
) -> str:
    split = urlsplit(search_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    los = (check_out_date - check_in_date).days
    query.update(
        {
            "checkIn": check_in_date.isoformat(),
            "checkOut": check_out_date.isoformat(),
            "los": str(los),
            "rooms": str(rooms),
            "adults": str(adults),
            "children": str(children),
            "textToSearch": destination,
        }
    )
    if rich:
        query.update(
            {
                "cid": query.get("cid", "-1"),
                "finalPriceView": "1",
                "isShowMobileAppPrice": "false",
                "familyMode": "false",
                "maxRooms": "0",
                "childAges": "",
                "numberOfGuest": "0",
                "missingChildAges": "false",
                "travellerType": "1",
                "showReviewSubmissionEntry": "false",
                "currencyCode": query.get("currencyCode", "VND"),
                "isFreeOccSearch": "false",
            }
        )
    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            split.path,
            urlencode(query, doseq=True),
            "",
        )
    )


def parse_iso_date(value: str, label: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD: {value}") from exc
