# Data contract và quality rules

## Output JSONL

Mỗi dòng là một object JSON. File có tên:

```text
<output-dir>/agoda_hotels_<check-in>.jsonl
```

Các field public:

```text
hotel_name, hotel_url, price_value, rating_text, review_count_text,
star_rating_text, crawled_at, destination,
normalized_destination, check_in, check_out
```

Ba field bắt buộc là:

```text
hotel_name, hotel_url, price_value
```

Record thiếu một trong ba field này không được ghi vào JSONL public. Nó chỉ được lưu để debug trong `debug/discarded_records.json`; job vẫn kết thúc thành công và ghi cảnh báo trong summary.

`rating_text`, `review_count_text`, và `star_rating_text` là optional. Record thiếu các field này vẫn được ghi ra JSONL nếu đủ ba field bắt buộc.

## Coverage optional

Mỗi field optional phải có coverage **lớn hơn** ngưỡng cấu hình. Mặc định là `90`, nghĩa là coverage đúng `90.0%` vẫn là warning; chỉ `> 90.0%` mới pass.

```text
AGODA_MIN_OPTIONAL_COVERAGE=90
```

Coverage thấp không làm process fail. Kiểm tra các dòng sau trong output:

```text
VERIFY_RATING_COVERAGE=
VERIFY_REVIEW_COUNT_COVERAGE=
VERIFY_STAR_RATING_COVERAGE=
VERIFY_OPTIONAL_COVERAGE_STATUS=
VERIFY_DISCARDED_RECORDS=
```

## Dedupe

Thứ tự identity ưu tiên là `canonical_url`, URL chuẩn hóa, `listing_property_id`, rồi fallback `hotel_name`. Merge chỉ bổ sung field đang thiếu; không ghi đè dữ liệu đã có. Vì vậy tổng `page_records` có thể cao hơn tổng record cuối khi Agoda lặp listing giữa các page.

## Detail enrichment

Detail chỉ chạy khi bật `--enrich-details` và record thiếu một field nằm trong `--detail-fields`. Default detail fields là:

```text
price_value,rating_text,review_count_text
```

`star_rating_text` là optional theo default. Nếu thêm nó vào `--detail-fields`, nhiều record có thể phải mở trang detail; đánh giá chi phí runtime trước khi bật toàn bộ.

## Quy tắc khi thay đổi code

1. Không đưa record thiếu `hotel_name`, `hotel_url`, hoặc `price_value` vào JSONL public.
2. Không coi `VERIFY_COVERAGE_STATUS=success` là đủ nếu `pages_collected` thấp hơn page yêu cầu hoặc có duplicate page.
3. Khi đổi selector/parser, thêm test fixture hoặc fake nhỏ cho format mới.
4. Không trộn benchmark runs vào cùng output directory vì JSONL append-only.
