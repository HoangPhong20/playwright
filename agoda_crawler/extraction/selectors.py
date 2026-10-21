"""Centralized selector definitions for Agoda scraper."""

LISTING_CARD_SELECTORS = [
    '[data-selenium="hotel-item"]',
    '[data-selenium="hotel-item-container"]',
    '[data-testid="property-card"]',
    '[data-testid="search-result-card"]',
    '[data-testid="hotel-card"]',
    '[data-element-name="property-card"]',
    '[data-element-name="hotel-item"]',
    'li[data-selenium="hotel-item"]',
]

BROAD_LISTING_CARD_SELECTORS = [
    'article:has(a[href*="/hotel/"])',
]

LISTING_MEMBERSHIP_BROAD_CARD_SELECTORS = [
    'article:has(a[href*="/hotel/"], a[href*="propertyId=" i])',
    'li[data-hotelid]',
    'li:has(a[href*="/hotel/"], a[href*="propertyId=" i])',
    'div[data-testid^="property-card" i]',
]

NON_LISTING_CONTEXT_SELECTOR_PARTS = [
        "footer",
        "nav",
        "aside",
        '[role="contentinfo"]',
        '[role="navigation"]',
        '[role="complementary"]',
        '[aria-label*="recommend" i]',
        '[data-testid*="recommend" i]',
        '[data-selenium*="recommend" i]',
        '[data-element-name*="recommend" i]',
        '[class*="recommend" i]',
        '[id*="recommend" i]',
        '[data-testid*="related-hotel" i]',
        '[data-selenium*="related-hotel" i]',
        '[class*="related-hotel" i]',
        '[id*="related-hotel" i]',
        '[class*="similar-hotel" i]',
        '[id*="similar-hotel" i]',
        '[aria-label*="you may also" i]',
        '[aria-label*="you might also" i]',
        '[data-testid*="you-might-also" i]',
        '[class*="you-might-also" i]',
        '[id*="you-might-also" i]',
        '[aria-label*="recently viewed" i]',
        '[data-testid*="recently-viewed" i]',
        '[class*="recently-viewed" i]',
        '[id*="recently-viewed" i]',
        '[data-testid*="you-may-also" i]',
        '[class*="you-may-also" i]',
        '[id*="you-may-also" i]',
    ]
NON_LISTING_CONTEXT_SELECTORS = ", ".join(NON_LISTING_CONTEXT_SELECTOR_PARTS)
NON_LISTING_CONTEXT_EXCLUSION_SELECTOR = ", ".join(
    selector
    for context_selector in NON_LISTING_CONTEXT_SELECTOR_PARTS
    for selector in (context_selector, f"{context_selector} *")
)

LISTING_CARD_MEMBERSHIP_CONFIG = {
    "strictCardSelector": ", ".join(LISTING_CARD_SELECTORS),
    "broadCardSelector": ", ".join(LISTING_MEMBERSHIP_BROAD_CARD_SELECTORS),
    "searchResultsRootSelector": ", ".join(
        [
            '[id*="search-results" i]',
            '[data-testid*="search-results" i]',
            '[data-selenium*="search-results" i]',
            '[class*="search-results" i]',
            '[id*="search-result-list" i]',
            '[data-testid*="search-result-list" i]',
            '[data-selenium*="search-result-list" i]',
            '[class*="search-result-list" i]',
        ]
    ),
    "mainRootSelector": 'main, [role="main"]',
    "excludedContextSelector": NON_LISTING_CONTEXT_SELECTORS,
}

LISTING_CARD_MEMBERSHIP_CLASSIFIER_JS = r"""
config => {
    const isExcluded = (element) => {
        let current = element;
        while (current && current.nodeType === 1) {
            if (current.matches(config.excludedContextSelector)) return true;
            current = current.parentElement;
        }
        return false;
    };
    const strictCards = Array.from(document.querySelectorAll(config.strictCardSelector))
        .filter((card) => !isExcluded(card));
    const hasStrictCard = (root) => strictCards.some((card) => (
        root === card || root.contains(card)
    ));
    const hasEligibleHotelAnchor = (element) => {
        const anchorSelector = 'a[href*="/hotel/"], a[href*="propertyId=" i]';
        const anchors = [];
        if (element.matches && element.matches(anchorSelector)) anchors.push(element);
        anchors.push(...Array.from(element.querySelectorAll(anchorSelector)));
        return anchors.some((anchor) => !isExcluded(anchor));
    };
    const searchRootNodes = Array.from(
        document.querySelectorAll(config.searchResultsRootSelector)
    );
    const verifiedSearchRoots = searchRootNodes.filter(hasStrictCard);
    const verifiedRoots = verifiedSearchRoots.length
        ? verifiedSearchRoots
        : searchRootNodes.length
            ? searchRootNodes
            : Array.from(document.querySelectorAll(config.mainRootSelector));
    return (element) => {
        if (!element || isExcluded(element)) return 'excluded';
        if (element.matches(config.strictCardSelector)) return 'strict';
        if (element.matches(config.broadCardSelector)) {
            if (!hasEligibleHotelAnchor(element)) return 'excluded';
            return verifiedRoots.some((root) => root === element || root.contains(element))
                ? 'verified_root'
                : 'unverified';
        }
        return 'unverified';
    };
}
"""

FIELD_SELECTORS = {
    "hotel_name": [
        '[data-selenium="hotel-name"]',
        '[data-testid="property-card-name"]',
        'a[href*="/hotel/"] span',
        'a[href*="/hotel/"] div',
        '[class*="PropertyCard"] h3',
        "h3",
        "h2",
    ],
    "hotel_link": [
        'a[data-selenium="hotel-name"]',
        '[data-testid="property-card"] a[href*="/hotel/"]',
        'article a[href*="/hotel/"]',
        'a[href*="/hotel/"]',
        "a",
    ],
    "price_value": [
        '[data-selenium="display-price"]',
        '[data-element-name="final-price"]',
        '[data-testid="price-and-discounted-price"]',
        '[data-testid="display-price"]',
        '[data-testid*="price" i]',
        '[data-selenium*="price" i]',
        '[data-element-name*="price" i]',
        '[aria-label*="price" i]',
        '[class*="price" i]',
    ],
    "rating_text": [
        '[data-selenium="review-score"]',
        '[data-testid="review-score"]',
        '[data-testid*="review"] [data-testid*="score"]',
        '[class*="ReviewScore"] [class*="Score"]',
        'div:has-text("Excellent")',
        'div:has-text("Exceptional")',
        'div:has-text("Very good")',
    ],
    "review_count_text": [
        '[data-selenium="review-count"]',
        '[data-testid="review-count"]',
        'span:has-text("reviews")',
    ],
    "star_rating_text": [
        '[data-selenium="hotel-star-rating"]',
        '[data-testid="star-rating"]',
        '[aria-label*="star rating" i]',
        '[class*="StarRating"]',
        '[aria-label*="star"]',
    ],
}

COOKIE_BUTTON_SELECTORS = [
    'button#onetrust-accept-btn-handler',
    'button:has-text("Accept")',
    'button:has-text("I agree")',
    'button[aria-label*="accept" i]',
]

DESTINATION_INPUT_SELECTORS = [
    '#textInput',
    'input[placeholder*="điểm du lịch" i]',
    'input[placeholder*="khách sạn" i]',
    'input[aria-label*="điểm du lịch" i]',
    'input[aria-label*="khách sạn" i]',
    '[data-selenium="destinationSearchInput"] input',
    'input[data-selenium="textInput"]',
    '[data-selenium="search-box"] input[placeholder]',
    '[class*="SearchBox"] input[placeholder]',
    'form[action*="search" i] input[placeholder]',
    'input[name*="destination" i]',
    'input[id*="destination" i]',
    'input[placeholder*="destination" i]',
    'input[placeholder*="property" i]',
]

NEXT_PAGE_SELECTORS = [
    "#paginationNext",
    '[data-selenium="pagination-next-btn"]',
    'button[aria-label*="Next"]',
    'button[aria-label*="next" i]',
    '[data-selenium="pagination-next"]',
    '[data-element-name="pagination-next"]',
    'a[aria-label*="Next"]',
    'a[aria-label*="next" i]',
    'button:has-text("Next")',
    'a:has-text("Next")',
    'button:has-text("Tiếp")',
    'a:has-text("Tiếp")',
]
