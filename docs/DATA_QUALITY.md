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

`price_value` is a positive integer amount in VND serialized as a string. Search
and detail URLs request `currencyCode=VND`; the parser rejects foreign currency,
negative/accounting values, zero, and decimal or ambiguously grouped amounts.
The UI parser accepts periods, commas, and spaces as VND thousands separators
when every group after the first contains three digits, then emits digits only
in public JSONL. Silver requires a positive digit-only value that fits
`decimal(18,0)`; it rejects signs, separators, currency text and overflow
instead of stripping them into another amount.

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

## Gold publication status

Gold refresh overwrites four tables sequentially. Its existing audit row moves
through `running` and then `success` or `failed`; a crash may leave `running`.
Partial failure can leave mixed table versions. Consumers must wait for the
relevant Job and Gold audit to succeed and avoid reading during another
refresh. An older successful audit is insufficient during a newer failed or
running refresh. See the [publication contract](../databricks/README.md#gold-publication).

## Dedupe

Thứ tự identity ưu tiên là `canonical_url`, URL chuẩn hóa, `listing_property_id`, rồi fallback `hotel_name`. Merge chỉ bổ sung field đang thiếu; không ghi đè dữ liệu đã có. Vì vậy tổng `page_records` có thể cao hơn tổng record cuối khi Agoda lặp listing giữa các page.

Agoda canonical URL keys retain a numeric `propertyId` query parameter because
multiple properties can share the same path. Stay dates and tracking parameters
do not affect that key. Observations with the same property identity merge in
either order; different property IDs remain separate even when the display name
matches.

## Pagination completeness

The manifest records one outcome for every planned destination and stay in
`jobs`, including jobs that return no records. A job is complete when it reaches
its configured `max_pages` upper bound or the visible pagination controls
confirm the end of results. A lower page count is valid when the site confirms
the end; it is not required to equal `max_pages`.

Navigation failures, duplicate-page exhaustion, and the low-new-record heuristic
are recorded as failed or incomplete outcomes. The heuristic still stops early,
but it does not prove that Agoda returned every page. Downstream validation
rejects any incomplete job when the `jobs` field is present. Older complete
manifests without `jobs` keep their prior validation behavior.

## Detail enrichment

Detail chỉ chạy khi bật `--enrich-details` và record thiếu một field nằm trong `--detail-fields`. Default detail fields là:

```text
price_value,rating_text,review_count_text
```

`star_rating_text` là optional theo default. Nếu thêm nó vào `--detail-fields`, nhiều record có thể phải mở trang detail; đánh giá chi phí runtime trước khi bật toàn bộ.

## Quy tắc khi thay đổi code

1. Không đưa record thiếu `hotel_name`, `hotel_url`, hoặc `price_value` vào JSONL public.
2. Use the per-job manifest outcome to assess pagination; a confirmed end of
   results may collect fewer pages than the configured upper bound, while a
   low-new-record stop or failed transition must not be published as complete.
3. Khi đổi selector/parser, thêm test fixture hoặc fake nhỏ cho format mới.
4. Không dùng lại cùng `airflow_run_id` và `airflow_try_number` cho benchmark;
   mỗi attempt directory là immutable.
