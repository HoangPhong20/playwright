"""Configuration helpers and environment-backed defaults."""

import os
from pathlib import Path
from typing import Dict


DEFAULT_LOCALE = "vi-vn"
ENV_PATH = ".env"

# Safe fallbacks for optional .env settings. Runtime values are still read from
# .env (or process environment) by main.py before each crawler invocation.
DEFAULT_DESTINATION = "Vung Tau"
DEFAULT_DESTINATIONS = "Vung Tau,Da Nang,Nha Trang,Ho Chi Minh"
DEFAULT_MAX_PAGES = 5
DEFAULT_WORKERS = 3
DEFAULT_DETAIL_CONCURRENCY = 2
DEFAULT_TOTAL_DETAIL_CONCURRENCY = 3
DEFAULT_DETAIL_TIMEOUT = 30_000
DEFAULT_FIELD_RETRY_TIMEOUT = 1_500
DEFAULT_FIELD_RETRY_COUNT = 2
DEFAULT_MAX_SCROLL_ROUNDS = 80
DEFAULT_STABLE_ROUNDS = 3
DEFAULT_SCROLL_WAIT_MS = 1_000
DEFAULT_DETAIL_FIELDS = "price_value,rating_text,review_count_text"

CONFIG_ENV_KEYS = {
    "AGODA_MAX_PAGES",
    "AGODA_HEADLESS",
    "AGODA_DESTINATION",
    "AGODA_DESTINATIONS",
    "AGODA_ADULTS",
    "AGODA_ROOMS",
    "AGODA_CHILDREN",
    "AGODA_LOCALE",
    "AGODA_OUTPUT_DIR",
    "AGODA_ENRICH_DETAILS",
    "AGODA_MAX_DETAIL_PAGES",
    "AGODA_WORKERS",
    "AGODA_DETAIL_CONCURRENCY",
    "AGODA_TOTAL_DETAIL_CONCURRENCY",
    "AGODA_DETAIL_TIMEOUT",
    "AGODA_DETAIL_FIELDS",
    "AGODA_FIELD_RETRY_TIMEOUT",
    "AGODA_FIELD_RETRY_COUNT",
    "AGODA_DETAIL_PROGRESS_INTERVAL",
    "AGODA_ENRICH_MISSING_ONLY",
    "AGODA_MIN_OPTIONAL_COVERAGE",
    "AGODA_MAX_SCROLL_ROUNDS",
    "AGODA_STABLE_ROUNDS",
    "AGODA_SCROLL_WAIT_MS",
    "AGODA_PRINT_RECORDS",
    "AGODA_CLICK_SHORT",
    "AGODA_CLICK_DEFAULT",
    "AGODA_CLICK_NEXT_PAGE",
    "AGODA_LOAD_PAGE",
    "AGODA_LOAD_HOMEPAGE",
    "AGODA_WAIT_STABLE_LOAD_TIMEOUT",
    "AGODA_WAIT_STABLE_SETTLE",
    "AGODA_WAIT_AFTER_COOKIE",
    "AGODA_WAIT_AFTER_SEARCH",
    "AGODA_WAIT_AFTER_NAV",
    "AGODA_WAIT_BEFORE_SCRAPE",
    "AGODA_CARDS_POLL_INTERVAL",
    "AGODA_CARDS_TIMEOUT",
    "AGODA_CARDS_TIMEOUT_RETRY",
    "AGODA_URL_FALLBACK_CARDS_TIMEOUT",
    "AGODA_SEARCH_ATTEMPTS",
    "AGODA_SEARCH_READY_TIMEOUT",
    "AGODA_SEARCH_LISTING_READY_TIMEOUT",
    "AGODA_MIN_PAGE_HOTELS_BEFORE_STABLE",
    "AGODA_MIN_PAGE_HOTELS_BEFORE_TIME_CAP",
    "AGODA_MAX_LISTING_PAGE_SECONDS",
    "AGODA_MIN_PAGE_HOTELS_BEFORE_FALLBACK",
    "AGODA_LISTING_FULL_SNAPSHOT_INTERVAL",
    "AGODA_LOW_NEW_RECORD_THRESHOLD",
    "AGODA_LOW_NEW_RECORD_ROUNDS",
    "AGODA_LAZY_NETWORK_IDLE_TIMEOUT",
    "AGODA_LAZY_SETTLE_WAIT",
    "AGODA_SCROLL_WHEEL_DELTA",
    "AGODA_SCROLL_VIEWPORT_PERCENT",
    "AGODA_SCROLL_USE_PAGEDOWN",
    "AGODA_SAVE_DEBUG_ARTIFACTS",
    "AGODA_BLOCK_RESOURCE_TYPES",
    "AGODA_BLOCK_URL_KEYWORDS",
    "AGODA_AIRFLOW_SCHEDULE",
    "AGODA_AIRFLOW_TIMEZONE",
    "AGODA_CHECK_IN_OFFSET_DAYS",
    "AGODA_AIRFLOW_OUTPUT_DIR",
    "AGODA_LOCAL_RETENTION_DAYS",
    "AGODA_AIRFLOW_RETRIES",
    "AGODA_AIRFLOW_RETRY_DELAY_MINUTES",
}


def load_dotenv(path: str = ENV_PATH) -> Dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}

    values: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()

        key, separator, value = line.partition("=")
        if not separator:
            continue

        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_config_env(path: str = ENV_PATH) -> Dict[str, str]:
    values = load_dotenv(path)
    unknown_keys = sorted(
        key for key in values if key.startswith("AGODA_") and key not in CONFIG_ENV_KEYS
    )
    if unknown_keys:
        raise ValueError(f"Unsupported .env configuration key(s): {', '.join(unknown_keys)}")
    for key in CONFIG_ENV_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def env_int(env: Dict[str, str], key: str, default: int) -> int:
    value = env.get(key)
    return default if value is None else int(value)


def env_bool(env: Dict[str, str], key: str, default: bool) -> bool:
    value = env.get(key)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{key} must be a boolean value: {value}")


def env_float(env: Dict[str, str], key: str, default: float) -> float:
    value = env.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{key} must be a number: {value}") from exc


def env_csv(env: Dict[str, str], key: str, default: str) -> tuple[str, ...]:
    value = env.get(key, default)
    return tuple(part.strip() for part in value.split(",") if part.strip())


_ENV = load_config_env()

CLICK_SHORT = env_int(_ENV, "AGODA_CLICK_SHORT", 1_200)
CLICK_DEFAULT = env_int(_ENV, "AGODA_CLICK_DEFAULT", 2_000)
CLICK_NEXT_PAGE = env_int(_ENV, "AGODA_CLICK_NEXT_PAGE", 3_000)
DETAIL_TIMEOUT = env_int(_ENV, "AGODA_DETAIL_TIMEOUT", 30_000)
FIELD_RETRY_TIMEOUT = env_int(_ENV, "AGODA_FIELD_RETRY_TIMEOUT", 1_500)
FIELD_RETRY_COUNT = env_int(_ENV, "AGODA_FIELD_RETRY_COUNT", 2)
DETAIL_PROGRESS_INTERVAL = env_int(_ENV, "AGODA_DETAIL_PROGRESS_INTERVAL", 30)

LOAD_PAGE = env_int(_ENV, "AGODA_LOAD_PAGE", 30_000)
LOAD_HOMEPAGE = env_int(_ENV, "AGODA_LOAD_HOMEPAGE", 60_000)
WAIT_STABLE_LOAD_TIMEOUT = env_int(_ENV, "AGODA_WAIT_STABLE_LOAD_TIMEOUT", 8_000)
WAIT_STABLE_SETTLE = env_int(_ENV, "AGODA_WAIT_STABLE_SETTLE", 500)

WAIT_AFTER_COOKIE = env_int(_ENV, "AGODA_WAIT_AFTER_COOKIE", 500)
WAIT_AFTER_SEARCH = env_int(_ENV, "AGODA_WAIT_AFTER_SEARCH", 1_200)
WAIT_AFTER_NAV = env_int(_ENV, "AGODA_WAIT_AFTER_NAV", 1_500)
WAIT_BEFORE_SCRAPE = env_int(_ENV, "AGODA_WAIT_BEFORE_SCRAPE", 200)

CARDS_POLL_INTERVAL = env_int(_ENV, "AGODA_CARDS_POLL_INTERVAL", 500)
CARDS_TIMEOUT = env_int(_ENV, "AGODA_CARDS_TIMEOUT", 45_000)
CARDS_TIMEOUT_RETRY = env_int(_ENV, "AGODA_CARDS_TIMEOUT_RETRY", 20_000)
URL_FALLBACK_CARDS_TIMEOUT = env_int(_ENV, "AGODA_URL_FALLBACK_CARDS_TIMEOUT", 30_000)
SEARCH_ATTEMPTS = env_int(_ENV, "AGODA_SEARCH_ATTEMPTS", 2)
SEARCH_READY_TIMEOUT = env_int(_ENV, "AGODA_SEARCH_READY_TIMEOUT", 8_000)
SEARCH_LISTING_READY_TIMEOUT = env_int(
    _ENV,
    "AGODA_SEARCH_LISTING_READY_TIMEOUT",
    5_000,
)

MAX_SCROLL_ROUNDS = env_int(_ENV, "AGODA_MAX_SCROLL_ROUNDS", 80)
STABLE_ROUNDS = env_int(_ENV, "AGODA_STABLE_ROUNDS", 3)
SCROLL_WAIT_MS = env_int(_ENV, "AGODA_SCROLL_WAIT_MS", 1_000)
MIN_OPTIONAL_COVERAGE = env_float(_ENV, "AGODA_MIN_OPTIONAL_COVERAGE", 90.0)
if not 0 <= MIN_OPTIONAL_COVERAGE <= 100:
    raise ValueError("AGODA_MIN_OPTIONAL_COVERAGE must be between 0 and 100")
MIN_PAGE_HOTELS_BEFORE_STABLE = env_int(_ENV, "AGODA_MIN_PAGE_HOTELS_BEFORE_STABLE", 100)
MIN_PAGE_HOTELS_BEFORE_TIME_CAP = env_int(_ENV, "AGODA_MIN_PAGE_HOTELS_BEFORE_TIME_CAP", 60)
MAX_LISTING_PAGE_SECONDS = env_int(_ENV, "AGODA_MAX_LISTING_PAGE_SECONDS", 240)
MIN_PAGE_HOTELS_BEFORE_FALLBACK = env_int(_ENV, "AGODA_MIN_PAGE_HOTELS_BEFORE_FALLBACK", 70)
LISTING_FULL_SNAPSHOT_INTERVAL = env_int(_ENV, "AGODA_LISTING_FULL_SNAPSHOT_INTERVAL", 10)
LOW_NEW_RECORD_THRESHOLD = env_int(_ENV, "AGODA_LOW_NEW_RECORD_THRESHOLD", 10)
LOW_NEW_RECORD_ROUNDS = env_int(_ENV, "AGODA_LOW_NEW_RECORD_ROUNDS", 2)
LAZY_NETWORK_IDLE_TIMEOUT = env_int(_ENV, "AGODA_LAZY_NETWORK_IDLE_TIMEOUT", 300)
LAZY_SETTLE_WAIT = env_int(_ENV, "AGODA_LAZY_SETTLE_WAIT", 100)
SCROLL_WHEEL_DELTA = env_int(_ENV, "AGODA_SCROLL_WHEEL_DELTA", 1_600)
SCROLL_VIEWPORT_PERCENT = env_int(_ENV, "AGODA_SCROLL_VIEWPORT_PERCENT", 100)
SCROLL_USE_PAGEDOWN = env_bool(_ENV, "AGODA_SCROLL_USE_PAGEDOWN", False)
SAVE_DEBUG_ARTIFACTS = env_bool(_ENV, "AGODA_SAVE_DEBUG_ARTIFACTS", False)

BLOCK_RESOURCE_TYPES = env_csv(_ENV, "AGODA_BLOCK_RESOURCE_TYPES", "image,font,media")
BLOCK_URL_KEYWORDS = env_csv(
    _ENV,
    "AGODA_BLOCK_URL_KEYWORDS",
    "googletagmanager,google-analytics,doubleclick,facebook,hotjar,clarity,taboola",
)
