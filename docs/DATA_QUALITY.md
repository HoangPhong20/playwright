# Data contract và quality rules

## Run isolation

Public JSONL paths are scoped to one execution:

```text
<output-dir>/dag_id=<id>/batch_id=<id>/attempt=<number>/
  agoda_hotels_<check-in>.jsonl
  run_manifest.json
```

The directory includes `run_manifest.json`; debug diagnostics are scoped under
`debug/<batch-id>/<destination>/<check-in>/` and
`debug/<batch-id>/summary/<check-in>/`. This prevents reruns from mixing output
records or overwriting pagination evidence from concurrent destinations.

## Output JSONL

Public JSONL is business-only. Airflow batch metadata is supplied by the
manifest and is appended by Bronze, not emitted on each crawler record.

Mỗi dòng là một object JSON. File có tên:

```text
<output-dir>/dag_id=<id>/batch_id=<id>/attempt=<number>/agoda_hotels_<check-in>.jsonl
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

Record thiếu một trong ba field này không được ghi vào JSONL public. Nó chỉ
được lưu để debug trong
`debug/<batch-id>/summary/<check-in>/discarded_records.json`; job vẫn kết thúc
thành công và ghi cảnh báo trong summary.

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

## Databricks Bronze and Silver quality gates

The versioned source contract is `databricks/contracts/agoda_hotel.yaml`.
Bronze reads each JSONL line permissively. Unknown fields and source scalar
representation changes are retained in `raw_record_json`; only a malformed JSON
line is quarantined at this boundary. Bronze also verifies that the physical
line count exactly matches the `publishable_records` declared by the manifest.

The YAML contract is enforced in Silver. Required fields, URL, positive-price,
timestamp, check-in/check-out, rating, review-count, star-rating, and
cross-field rules are evaluated from the contract there. Invalid rows remain in
Bronze and are written to quarantine with `quarantine_layer = silver`. Silver
fails only after quarantine when invalid records exceed 10% of input or 200
records.

Use these Unity Catalog tables to investigate a run:

```text
agoda.raw.agoda_hotel_quarantine
agoda.raw.agoda_pipeline_audit
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
4. Không dùng lại cùng `airflow_run_id` và `airflow_try_number` cho benchmark;
   mỗi attempt directory là immutable.
