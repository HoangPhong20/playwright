from agoda_crawler.utils.page_helpers import wait_for_cards


class _FakeLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class _FakePage:
    def __init__(self, counts: dict[str, int]) -> None:
        self._counts = counts

    def is_closed(self) -> bool:
        return False

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self._counts.get(selector, 0))


def test_wait_for_cards_prefers_strict_listing_selector() -> None:
    page = _FakePage(
        {
            '[data-testid="property-card"]': 2,
            'article:has(a[href*="/hotel/"])': 8,
        }
    )

    selector = wait_for_cards(page, timeout_ms=1_000)

    assert selector == '[data-testid="property-card"]'
