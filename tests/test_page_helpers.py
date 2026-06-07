from agoda_crawler.utils.page_helpers import handle_page_popups, wait_for_cards


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


class _WaitFunctionPage(_FakePage):
    def __init__(self) -> None:
        super().__init__({})
        self.wait_calls = []

    def wait_for_function(self, expression: str, *, arg, timeout: int) -> None:
        self.wait_calls.append((arg, timeout))
        self._counts['[data-testid="property-card"]'] = 1


def test_wait_for_cards_uses_page_wait_api_before_polling() -> None:
    page = _WaitFunctionPage()

    selector = wait_for_cards(page, timeout_ms=4_000)

    assert selector == '[data-testid="property-card"]'
    assert page.wait_calls


class _PopupLocator:
    def __init__(self, page, selector: str) -> None:
        self._page = page
        self._selector = selector

    @property
    def first(self):
        return self

    def count(self) -> int:
        return self._page.counts.get(self._selector, 0)

    def click(self, timeout: int) -> None:
        self._page.clicked.append((self._selector, timeout))
        if self._page.raise_on_click:
            raise RuntimeError("blocked")
        self._page.counts[self._selector] = 0


class _PopupPage:
    def __init__(self, counts: dict[str, int], raise_on_click: bool = False) -> None:
        self.counts = counts
        self.clicked = []
        self.waited = []
        self.raise_on_click = raise_on_click

    def locator(self, selector: str) -> _PopupLocator:
        return _PopupLocator(self, selector)

    def wait_for_timeout(self, timeout_ms: int) -> None:
        self.waited.append(timeout_ms)


def test_handle_page_popups_clicks_close_selector() -> None:
    page = _PopupPage({'button[aria-label*="close" i]': 1})

    handle_page_popups(page)

    assert page.clicked[0][0] == 'button[aria-label*="close" i]'
    assert page.waited


def test_handle_page_popups_ignores_click_failures() -> None:
    page = _PopupPage({'button[aria-label*="close" i]': 1}, raise_on_click=True)

    handle_page_popups(page)

    assert page.clicked[0][0] == 'button[aria-label*="close" i]'
