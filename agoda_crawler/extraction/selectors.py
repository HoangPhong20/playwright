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
    "image_url": [
        "img",
        "[data-testid='property-card-image'] img",
    ],
}

COOKIE_BUTTON_SELECTORS = [
    'button#onetrust-accept-btn-handler',
    'button:has-text("Accept")',
    'button:has-text("I agree")',
    'button[aria-label*="accept" i]',
]

PAGE_POPUP_BUTTON_SELECTORS = [
    *COOKIE_BUTTON_SELECTORS,
    'button[aria-label*="close" i]',
    '[role="button"][aria-label*="close" i]',
    'button[data-testid*="close" i]',
    '[data-testid*="close" i]',
    'button[data-selenium*="close" i]',
    '[data-selenium*="close" i]',
    'button[data-element-name*="close" i]',
    '[data-element-name*="close" i]',
    '[data-testid*="login" i] button[aria-label*="close" i]',
    '[data-selenium*="login" i] button[aria-label*="close" i]',
    '[data-testid*="language" i] button[aria-label*="close" i]',
    '[data-testid*="currency" i] button[aria-label*="close" i]',
    '[data-testid*="promotion" i] button[aria-label*="close" i]',
    '[role="dialog"] button:has-text("Close")',
    '[role="dialog"] button:has-text("OK")',
    '[role="dialog"] button:has-text("No thanks")',
    '[role="dialog"] button:has-text("Maybe later")',
    '[aria-modal="true"] button:has-text("Close")',
    '[aria-modal="true"] button:has-text("OK")',
    '[aria-modal="true"] button:has-text("No thanks")',
    '[aria-modal="true"] button:has-text("Maybe later")',
    '[class*="modal" i] button:has-text("Close")',
    '[class*="modal" i] button:has-text("OK")',
    '[class*="modal" i] button:has-text("No thanks")',
    '[class*="modal" i] button:has-text("Maybe later")',
    'button:has-text("No thanks")',
    'button:has-text("Maybe later")',
    'button:has-text("Not now")',
    'button:has-text("Skip")',
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
