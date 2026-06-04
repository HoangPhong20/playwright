from agoda_crawler.utils.resource_blocking import apply_resource_blocking


class _FakeRequest:
    def __init__(self, resource_type: str, url: str) -> None:
        self.resource_type = resource_type
        self.url = url


class _FakeRoute:
    def __init__(self, resource_type: str, url: str) -> None:
        self.request = _FakeRequest(resource_type, url)
        self.action = None

    def abort(self) -> None:
        self.action = "abort"

    def continue_(self) -> None:
        self.action = "continue"


class _FakeContext:
    def __init__(self) -> None:
        self.pattern = None
        self.handler = None

    def route(self, pattern: str, handler) -> None:
        self.pattern = pattern
        self.handler = handler


def test_apply_resource_blocking_aborts_blocked_resource_type() -> None:
    context = _FakeContext()

    apply_resource_blocking(context, resource_types=("image",), url_keywords=())
    route = _FakeRoute("image", "https://img.agoda.net/hotel.jpg")
    context.handler(route)

    assert context.pattern == "**/*"
    assert route.action == "abort"


def test_apply_resource_blocking_aborts_keyword_url() -> None:
    context = _FakeContext()

    apply_resource_blocking(
        context,
        resource_types=(),
        url_keywords=("doubleclick",),
    )
    route = _FakeRoute("script", "https://stats.doubleclick.net/pixel.js")
    context.handler(route)

    assert route.action == "abort"


def test_apply_resource_blocking_continues_allowed_request() -> None:
    context = _FakeContext()

    apply_resource_blocking(context, resource_types=("font",), url_keywords=("ads",))
    route = _FakeRoute("document", "https://www.agoda.com/search")
    context.handler(route)

    assert route.action == "continue"
