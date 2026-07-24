"""Text, URL, and price parsers used by Agoda extraction."""
import re
import unicodedata
from typing import Dict, Optional
from urllib.parse import urlparse, urlunparse

from agoda_crawler.utils import compact_text


def raw_snippet(text: Optional[str], max_len: int = 800) -> Optional[str]:
    if not text:
        return None
    snippet = re.sub(r"\s+", " ", text).strip()
    return snippet[:max_len] if snippet else None


def normalize_review_score(value: str) -> Optional[str]:
    normalized = value.replace(",", ".")
    try:
        score = float(normalized)
    except ValueError:
        return None
    if 5.0 <= score <= 10.0:
        return f"{score:.1f}"
    return None


def ascii_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.replace("\u0111", "d").replace("\u0110", "D")


def parse_review_score(text: str) -> Optional[str]:
    for match in re.finditer(r"\b(\d{1,2}(?:[.,]\d)?)\s*/\s*10\b", text):
        score = normalize_review_score(match.group(1))
        if score:
            return score

    normalized_text = ascii_text(text)
    rating_words = (
        r"tuyet voi|tren ca tuyet voi|rat tot|rat tuyet|hai long|"
        r"excellent|exceptional|very good|wonderful|good"
    )
    contextual_patterns = [
        rf"(?:{rating_words}).{{0,80}}?\b(\d{{1,2}}[.,]\d)\b",
        rf"\b(\d{{1,2}}[.,]\d)\b.{{0,80}}?(?:{rating_words})",
    ]
    for pattern in contextual_patterns:
        match = re.search(pattern, normalized_text, flags=re.IGNORECASE)
        if match:
            score = normalize_review_score(match.group(1))
            if score:
                return score

    return None


def parse_review_count(text: str) -> Optional[str]:
    normalized_text = ascii_text(text)
    match = re.search(
        r"\b([\d.,]+)\s*(?:bai\s+)?(?:danh gia|nhan xet|reviews?)\b",
        normalized_text,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def parse_star_rating(text: str) -> Optional[str]:
    normalized_text = ascii_text(text)
    match = re.search(
        r"\b(\d(?:[.,]\d)?)\s*(?:sao|stars?)\s*(?:tren|out\s+of)\s*5\b",
        normalized_text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return f"{match.group(1).replace(',', '.')} stars"


def price_value_from_text(text: str) -> Optional[str]:
    candidate = extract_price_candidate(text)
    return canonicalize_price_value(candidate) if candidate else None


def extract_price_candidate(text: str) -> Optional[str]:
    if not text:
        return None

    normalized_text = compact_text(text) or ""
    if not normalized_text:
        return None

    ascii_value = ascii_text(normalized_text)
    amount_with_currency = (
        r"(?:"
        r"(?:\b(?:VND|USD|EUR|GBP|JPY|KRW|THB|SGD|AUD|CAD|CNY|HKD)\b|₫)"
        r"\s*[\d][\d.,\s]*[\d]"
        r"|"
        r"[\d][\d.,\s]*[\d]\s*"
        r"(?:\b(?:VND|USD|EUR|GBP|JPY|KRW|THB|SGD|AUD|CAD|CNY|HKD)\b|₫|đ\b)"
        r")"
    )
    per_night_pattern = r"(?i)(?:per\s+night|moi\s+dem|mỗi\s+đêm|/dem|/đêm|\bdem\b|\bđêm\b)"

    for source_text in (normalized_text, ascii_value):
        best_candidate = None
        best_distance = None
        for match in re.finditer(amount_with_currency, source_text, flags=re.IGNORECASE):
            tail = source_text[match.end():match.end() + 120]
            context = re.search(per_night_pattern, tail, flags=re.IGNORECASE)
            if not context:
                continue
            distance = context.start()
            if best_distance is None or distance < best_distance:
                best_candidate = compact_text(match.group(0))
                best_distance = distance
        if best_candidate:
            return best_candidate

    patterns = [
        r"(?i)\b(?:VND|USD|EUR|GBP|JPY|KRW|THB|SGD|AUD|CAD|CNY|HKD)\b\s*([\d][\d.,\s]*[\d])",
        r"([\d][\d.,\s]*[\d])\s*(?i:\b(?:VND|USD|EUR|GBP|JPY|KRW|THB|SGD|AUD|CAD|CNY|HKD)\b)",
        r"([\d][\d.,\s]*[\d])\s*(?:₫|đ\b)",
        r"₫\s*([\d][\d.,\s]*[\d])",
        r"(?i)(?:price|gia|per night|moi dem|tong cong|total).{0,80}?((?:[\d][\d.,\s]*[\d])\s*(?:VND|USD|EUR|GBP|JPY|KRW|THB|SGD|AUD|CAD|CNY|HKD|₫|đ\b)|(?:VND|USD|EUR|GBP|JPY|KRW|THB|SGD|AUD|CAD|CNY|HKD|₫)\s*[\d][\d.,\s]*[\d])",
    ]

    for source_text in (normalized_text, ascii_value):
        for pattern in patterns:
            match = re.search(pattern, source_text, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = compact_text(match.group(0))
            if candidate:
                return candidate

    return None


def canonicalize_price_value(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    text = compact_text(value)
    if not text:
        return None

    currency_map = {
        "VND": [r"(?i)\bVND\b", r"\u20ab", r"\u0111"],
        "USD": [r"(?i)\bUSD\b"],
        "EUR": [r"(?i)\bEUR\b"],
        "GBP": [r"(?i)\bGBP\b"],
        "JPY": [r"(?i)\bJPY\b"],
        "KRW": [r"(?i)\bKRW\b"],
        "THB": [r"(?i)\bTHB\b"],
        "SGD": [r"(?i)\bSGD\b"],
        "AUD": [r"(?i)\bAUD\b"],
        "CAD": [r"(?i)\bCAD\b"],
        "CNY": [r"(?i)\bCNY\b"],
        "HKD": [r"(?i)\bHKD\b"],
    }

    currency = None
    for normalized_currency, patterns in currency_map.items():
        if any(re.search(pattern, text) for pattern in patterns):
            currency = normalized_currency
            break
    if not currency:
        return None

    amount_match = re.search(r"([\d][\d.,\s]*[\d])", text)
    if not amount_match:
        return None

    amount = amount_match.group(1)
    cleaned_amount = re.sub(r"\s+", "", amount)
    cleaned_amount = cleaned_amount.replace(",", "")
    cleaned_amount = cleaned_amount.replace(".", "")
    cleaned_amount = re.sub(r"[^\d]", "", cleaned_amount)
    if not cleaned_amount:
        return None

    minimum_digits = 4 if currency == "VND" else 2
    if len(cleaned_amount) < minimum_digits:
        return None

    return cleaned_amount


def hotel_url_key(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower()
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", ""))


def parse_textual_fallback(raw_text: Optional[str]) -> Dict[str, Optional[str]]:
    if not raw_text:
        return {
            "price_value": None,
            "rating_text": None,
            "review_count_text": None,
            "star_rating_text": None,
        }

    text = compact_text(raw_text) or ""

    rating_text = parse_review_score(text)
    star_match = re.search(r"\b(\d(?:\.\d)?)\s+stars?\s+out\s+of\s+5\b", text, flags=re.IGNORECASE)
    price_value = price_value_from_text(text)

    return {
        "price_value": price_value,
        "rating_text": rating_text,
        "review_count_text": parse_review_count(text),
        "star_rating_text": (star_match.group(1) + " stars") if star_match else parse_star_rating(text),
    }


def name_from_hotel_url(url: str) -> str:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    try:
        hotel_index = path_parts.index("hotel")
    except ValueError:
        hotel_index = -1

    slug = path_parts[hotel_index - 1] if hotel_index > 0 else path_parts[-1] if path_parts else "Unknown hotel"
    name = re.sub(r"[-_]+", " ", slug).strip()
    return name.title() if name else "Unknown hotel"
