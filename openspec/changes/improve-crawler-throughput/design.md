# Design

## Context

Xem [proposal.md](proposal.md) và [spec](specs/crawler-throughput/spec.md) cho động cơ và contract. Khảo sát ngày 20/10/2026: nhánh `update`, worktree sạch trước khi tạo artifacts, HEAD `0e700e522c8e71851d3d964e844cd1c98ab97691`. Đây là trạng thái lúc lập plan; bước apply phải kiểm tra lại, không coi hash này là source của benchmark tương lai.

Các bằng chứng quyết định thiết kế:

| Nguồn | Hiện trạng cần xử lý |
| --- | --- |
| `agoda_crawler/listing/collection.py` | `raw_cards + embedded_cards` tạo candidates; scan embedded đọc HTML toàn trang; mọi card tạo `outerHtmlPreview`. |
| `agoda_crawler/listing/collection.py::_looks_like_non_hotel_dom` | HTML preview còn tham gia lọc carousel/filter; không thể xóa như một field diagnostics thuần túy. |
| `agoda_crawler/listing/page_crawl.py` | Page result chưa có stop reason; max rounds có thể break trước scroll; snapshot cuối vẫn có thể bổ sung record/field. |
| `agoda_crawler/listing/pagination.py` | Tập URL khác nhau hoặc first hotel đổi có thể tính là content change, kể cả reorder/subset. |
| `agoda_crawler/extraction/fields.py::extract_detail_fields` | Đọc mọi field/body; rating/review dùng `review_text or raw_text`, bỏ qua body khi selector có text nhưng parse hỏng. |
| `agoda_crawler/enrichment/detail.py` | Retry gọi lại extraction toàn bộ fields; acquire global slot ở cấp worker/serial batch, không theo từng record. |
| `agoda_crawler/utils/run_output.py` | Summary nhận public records nên mất detail stats của discarded candidates; vòng cuộn lấy max từ record metadata. |
| `agoda_crawler/jobs.py`, `orchestration.py` | Đã có `CrawlJobResult.pagination` và job outcomes kể cả job rỗng; nên dùng kết quả job thay vì suy ngược từ public records. |
| `agoda_crawler/config.py`, `main.py` | Fallback code workers=3/detail=2/global=3 khác profile local 2/3/3. Benchmark phải truyền CLI tường minh. |

## Goals / Non-Goals

**Goals:** cô lập hiệu quả tối ưu bằng baseline có cùng correctness contract; metrics đủ phân biệt chi phí DOM, embedded, Python, chờ và detail; thay đổi nhỏ trong các module hiện có, không thêm framework đo đạc.

**Non-Goals:** xem [proposal.md](proposal.md#impact). Không biến time cap hiện có thành hard timeout, không coi Gold là atomic snapshot, không thay thiết kế thread/Sync API hoặc thuật toán dedupe hiện hữu.

## Decisions

### 1. Thứ tự và phương án chọn

Chọn luồng **metrics → correctness → smoke + hai baseline → detail → listing payload → smoke + ABBA → hai candidate full → quyết định mặc định**. Hai baseline cùng per-job=3, workers=2, global=3.

So với giữ baseline trước correctness, cách này tránh trộn lợi ích loại embedded ngoài phạm vi với hiệu quả giảm việc lặp. So với đổi kiến trúc async/pool hoặc tăng browser, cách này giữ phạm vi nhỏ và resource contract đã được test. Mốc lịch sử 19/10 chỉ là tham chiếu, không dùng làm mẫu số tính speedup mới.

Mọi package sửa code thực hiện tuần tự vì chia sẻ collection/extraction/enrichment; test lỗi trước, sửa nhỏ nhất, test lại rồi review. Theo AGENTS.md, khi apply sẽ giao code cho model hỗ trợ `gpt-6-luna`, `xhigh`; planning/review theo ưu tiên Sol 6.1 High nếu harness hỗ trợ. Không khẳng định có thể đổi model active session. Chỉ plan/docs được viết trong lượt hiện tại.

### 2. Membership ở cấp trang

- Dùng `records_by_key` tích lũy trong `crawl_current_results_page` làm tập quan sát của trang; full/regular snapshots phải thu hotel cards trước rồi mới xét embedded.
- Mở rộng `collect_listing_snapshot(..., *, observed_records: List[Dict] | None = None)`; snapshot độc lập vẫn dùng cards vừa thu. Truyền quan sát trước đó từ page crawl và probe. Chỉ records có nguồn hotel card được dùng làm gốc membership; embedded chỉ bổ sung record đó, không thêm gốc mới.
- So bằng `hotel_url_key` và `property_identity_value` hiện có, không tạo index dedupe mới. Nếu cả hai bên có property ID và khác nhau, từ chối dù URL khác dạng nhưng trông tương đồng. Tên/city suffix không quyết định membership.
- Partial card chỉ có tên vẫn được giữ; chưa đủ bằng chứng thì không tự gắn embedded URL. Merge partial/full theo quy tắc hiện có tiếp tục hoạt động khi xuất hiện full card thật.
- Embedded chưa khớp có thể được xét lại trong full scan sau; không giữ cache embedded toàn batch. Giữ tối đa 25 mẫu/trang, URL ≤500 ký tự; không dump toàn bộ HTML để làm mẫu membership.
- `extract_page_results`/`extract_from_hotel_links` ở fallback chỉ được bổ sung từ card container hợp lệ hoặc identity đã quan sát. Không dùng link recommendation/footer để tạo candidate. Probe cũng chịu quy tắc này.
- Báo `embedded_candidates_seen` theo số lần quan sát và `embedded_nonmember_unique` theo URL chuẩn hóa khác nhau trong trang; thêm `embedded_unmatched_at_end` để phân biệt URL đã khớp về sau. Không cộng số unique mỗi trang rồi gọi là unique toàn batch.

### 3. Dừng trang và completeness

Thêm `PageCrawlResult.stop_reason: str`, giá trị chỉ thuộc bốn loại dưới đây. Thuật toán quyết định dùng cùng record floor và stable rounds hiện hữu, không đổi wait/scroll config:

| Ưu tiên | Điều kiện sau snapshot xác nhận | Page reason | Job |
| --- | --- | --- | --- |
| 1 | Không có identity/field mới trong ≥stable rounds và không scroll được trong ≥stable rounds | `scroll_exhausted` | Trang thu xong |
| 2 | Không có identity/field mới trong ≥stable rounds và đủ `MIN_PAGE_HOTELS_BEFORE_STABLE` | `stable` | Trang thu xong |
| 3 | Chưa thu xong; cap>0, elapsed≥cap và đủ `MIN_PAGE_HOTELS_BEFORE_TIME_CAP` | `time_cap` | `incomplete` |
| 4 | Chưa thu xong và hết max rounds | `max_rounds` | `incomplete` |

Full snapshot cuối là bước xác nhận, không mặc định chứng minh hoàn tất. Nếu merge thêm identity/field thiếu, reset bộ đếm ổn định và tiếp tục trong số vòng/budget còn lại. Nếu hết budget thì incomplete. Không được lặp full snapshot vô hạn ngoài budget. Giữ fallback ít record nhưng kết quả fallback làm thay đổi dữ liệu cũng phải được xét lại theo quy tắc này.

Phân biệt `scroll_rounds` (vòng thu thập đã thực hiện, giữ nghĩa cũ) với `scroll_actions` (lần thực sự advance scroll). Thống kê tổng và max lấy từ page results, không dùng số record để suy ngược.

`crawler.py` xử lý stop reason ngay sau cả lần thu trang đầu và mọi candidate page: giữ records, page summary, diagnostics; nếu page chưa xong thì kết thúc job incomplete trước enrichment. `pages_collected` chỉ tăng cho trang đã thu xong/chấp nhận. Summary trang thu dở nằm trong `page_scroll_summaries` và page status riêng. Giữ job successful reasons `max_pages_reached`/`end_of_results`; page reason không thay job reason. Batch hiện chuyển failed khi có job incomplete và không publish pointer; giữ hành vi đó.

### 4. Pagination cần novelty thực sự

Mở rộng `pagination_change_evidence(previous, current, *, seen_identities: set[str] | None = None) -> Dict`. Nếu caller không truyền tập tích lũy thì dùng identity của previous để tương thích helper tests; crawler luôn truyền tập tích lũy của các trang đã chấp nhận. Novelty là phần identity mới sau canonical hóa/property identity, không phải set inequality đơn thuần.

Giữ năm tín hiệu cũ và ngưỡng ≥2; `verified` còn bắt buộc có identity mới. Chặn ở cả probe và full collection, không cập nhật tập accepted từ probe/trang bị từ chối. Giữ retry navigation, EOF có bằng chứng và các giới hạn hiện có. Bao gồm regression page1→page2→page1 và hai property cùng path khác ID.

### 5. Metrics và đường truyền

Thêm mapping metrics nhỏ vào kết quả sẵn có, không xây telemetry abstraction mới:

- `PageCrawlResult.work_metrics: Dict = field(default_factory=dict)`; `ListingCollectionMetrics` thêm các số đo snapshot.
- `CrawlJobResult.metrics: Dict = field(default_factory=dict)`.
- Hai API `crawl_agoda_search*` thêm `metrics_outcome: Optional[Dict] = None` cuối signature; `orchestration` truyền mapping riêng mỗi job.
- `enrich_records_from_details(..., metrics_outcome: Optional[Dict] = None)` và private worker nhận accumulator theo job; cập nhật phần chia sẻ trong lock hiện có. Slot wait serial ghi ở cấp serial batch; parallel ghi từng acquire của worker.
- Ghi `jobs[].metrics`, `stays[].metrics`, `summary` ở manifest và log tương ứng. Giữ fields/log cũ theo nghĩa cũ, bổ sung metrics toàn bộ ứng viên bằng tên riêng. Job rỗng/lỗi vẫn trả metrics qua finally, không nuốt exception hoặc thay trạng thái lỗi.

| Nhóm | Keys/ý nghĩa chuẩn |
| --- | --- |
| Batch | `batch_wall_seconds`: perf counter từ trước chuẩn bị worker/browser đến sau ghi outputs/summary, trước publish complete manifest/pointer; bao gồm mọi job và browser lifecycle, không lấy tổng job times. |
| Job wall | `search_wall_seconds`, `listing_wall_seconds`, `detail_wall_seconds`, `job_wall_seconds`; tổng giữa các job có thể lớn hơn batch wall. |
| Snapshot | `regular_snapshot_count`, `full_snapshot_count` là hai nhóm loại trừ nhau; `dom_call_seconds`, `embedded_call_seconds`, `parse_dedupe_seconds`, `merge_seconds`. DOM/embedded là wall time lời gọi Playwright gồm evaluate và truyền kết quả, không gọi là JS CPU time. |
| Listing | `active_wait_seconds` gồm waits chủ động/lazy waits; `other_seconds` gồm thao tác/overhead còn lại. Chi phí snapshot trong vòng chờ thuộc snapshot, không cộng vào active wait. `scroll_rounds_total`, `scroll_rounds_max`, `scroll_actions`. |
| Detail | `detail_candidates` trước giới hạn, `detail_scheduled` sau giới hạn, `detail_attempts` khi bắt đầu goto, `detail_failures` theo status failed, `field_retries` là số vòng retry đã thực hiện. Thêm `detail_missing_target_after_attempt` để không nhầm status success với đủ field. |
| Slot | `slot_acquire_count`, `slot_wait_seconds_sum`, `slot_wait_seconds_max`; không gán một acquire cho tất cả records của worker. |
| Detail work | `load_seconds_sum`, `extract_seconds_sum`, `record_seconds_sum` của mọi record đã thử, kể cả discarded. Các số này có thể chồng lấn giữa threads, không cộng vào batch wall. |
| Payload | `html_preview_count`, `html_preview_chars` đo số preview/kích thước tạo trước serialization để xác nhận phần việc đã bỏ. |

Đo `perf_counter()` đủ độ chính xác, chỉ round khi render/serialize; không dùng helper round 0,01s cho từng thao tác rồi cộng. Include mọi probe, fallback và rejected navigation attempt trong job cost; phân biệt page accepted với collection attempt để tránh gán nhầm. Không cộng raw snapshot counters/unique counts có nghĩa khác nhau.

Required-field discard tính từ tập record cuối sau merge: `discarded_records / total_records_after_merge`; embedded nonmember nằm ngoài mẫu số này và được báo riêng. Optional coverage tính trên public records như hiện có.

### 6. Detail extraction theo field

Signature chính thức:

```python
extract_detail_fields(
    page: Page, *, fields: tuple[str, ...] | None = None,
) -> Dict[str, Optional[str]]
```

`None` trả đủ năm keys hiện có; tuple trả đúng keys yêu cầu; `()` trả `{}` trước mọi DOM call. Field không được hỗ trợ báo `ValueError` trước DOM. Giữ re-export tại `extraction/__init__.py` và caller cũ không truyền `fields`.

Tập fields hợp lệ gồm `hotel_name`, `price_value`, `rating_text`, `review_count_text`, `star_rating_text`; enrichment targets vẫn ba field đã chốt. Nhóm selector detail nằm ở `extraction/selectors.py`; dùng chung text review cho rating/review chỉ khi một trong hai được yêu cầu. Parse từng field từ selector trước; chỉ nếu còn field thiếu mới đọc body một lần và parse phần thiếu. Giá VND, thứ tự ưu tiên và merge không ghi đè giữ nguyên.

`extract_detail_fields_with_field_retry` gọi lần đầu với tuple missing targets, retry với remaining tuple. Giữ số retry và timeout; cập nhật counter ngay khi vòng retry bắt đầu để lỗi extraction không làm mất số lần đã thử. `wait_for_any_detail_field` dùng locator kết hợp `.first.wait_for(state="attached", timeout=...)` cho toàn nhóm, không tuần tự chờ từng selector. Timeout≤0 hoặc fields rỗng trả ngay, tránh Playwright timeout=0 thành chờ vô hạn.

### 7. HTML preview chỉ khi cần, bằng chứng lọc độc lập

Trước khi bỏ preview, thay việc dùng chuỗi HTML làm bằng chứng filter/carousel bằng các cờ DOM có cùng tiêu chí: thuộc tính `aria-roledescription`, token class/attribute và nguồn selector hiện hữu. Cờ này truyền về cho pure Python classifier; không chuyển toàn bộ classifier sang JS.

Trong `_evaluate_listing_dom`, tạo preview cho card không có URL hợp lệ, có khả năng invalid hoặc khi bật debug; URL thô chưa chắc hợp lệ nên quyết định phải bảo thủ. Giữ tối đa 1.000 ký tự/preview như hiện có, sample invalid ≤25; card hợp lệ đầy đủ không tạo `outerHTML`. Nếu Python phát hiện trường hợp diagnostics không dự đoán được, lấy preview có mục tiêu cho card đó trong snapshot, không scan lại toàn bộ DOM. Không coi cờ lọc nhỏ là diagnostics có thể xóa.

Giữ interval full snapshot, regular before/after scroll và merge liên tục. Chưa cache payload, đổi wait, bỏ broad selectors hay thay stop heuristic. So sánh counters preview và timing trên baseline/candidate; synthetic chỉ chứng minh ít DOM reads/payload hơn, không chứng minh tốc độ live.

### 8. Profile, provenance và thu mẫu

Full profile tường minh: destinations theo thứ tự `Vung Tau,Da Nang,Nha Trang,Ho Chi Minh`, max_pages=5, workers=2, detail_total=3, detail_fields=`price_value,rating_text,review_count_text`, missing_only=true, enrich_details=true, max_detail_pages=0, locale=`vi-vn`, adults=2/rooms=1/children=0, headless=true. Baseline per-job=3; candidate là kết quả ABBA. Các setting scroll, timeouts, resource blocking, full interval, debug, optional coverage giữ cùng giá trị hiệu lực đã ghi trước run đầu; không phụ thuộc thay đổi `.env` giữa runs.

Chọn check-in một lần khi bắt đầu live validation, ví dụ `(Get-Date).AddDays(21)`; dùng lại giá trị đó cho toàn bộ series, checkout tự động +1 ngày. Không dùng ngày cố định đã hết hạn từ plan. Mỗi run dùng DAG `adhoc_throughput`, run ID mới, try=1 và output immutable; không dùng lại identity để so sánh.

Ghi cho từng run: command/CLI args đã loại bí mật, resolved AGODA settings trong whitelist và module constants, UTC start/end, commit SHA, git dirty flag, SHA-256 tập file nguồn theo thứ tự đường dẫn và từng file hash, fingerprint diff/untracked source liên quan nếu dirty, phiên bản Python/Playwright/Chromium và OS. Không đọc/log toàn bộ `.env`, cookie hoặc environment. Không đổi source/config trong một cặp baseline hoặc một series ABBA/candidate.

Phép đo CPU/RAM dùng sampler PowerShell local mô tả trong runbook, chu kỳ 5 giây; lấy cây tiến trình của crawler PID và Chromium con, bao gồm tiến trình xuất hiện sau lúc bắt đầu. Báo peak/sampled RSS và CPU-seconds, tách với RAM toàn máy; không chỉ đo Python. Sampler chạy độc lập, dừng sau run, không thêm dependency. Thiếu samples thì báo thiếu evidence và chưa quyết định mặc định; không tự cài profiler.

Artifacts runtime trong `data/benchmarks/<series-id>/` và output/debug hiện có đều ignored; tổng hợp bảng aggregate không có hotel raw records vào `docs/RUNBOOK.md`. Series ID/run ID/provenance nằm trong bảng để đối chiếu.

### 9. Ma trận benchmark và ngân sách

| Thứ tự | Source | Phạm vi | Workers / per-job / total | Lượt |
| --- | --- | --- | --- | --- |
| S0 | Metrics + correctness | Vũng Tàu × 1 trang, không detail | 1 / không dùng / 3 | 1 smoke |
| R1, R2 | Cùng source S0 | 4 thành phố × tối đa 5 trang | 2 / 3 / 3 | 2 full baseline |
| S1 | Tối ưu detail + payload | Vũng Tàu × 1 trang, không detail | 1 / không dùng / 3 | 1 smoke |
| A1, B1, B2, A2 | Cùng candidate source | Vũng Tàu + Đà Nẵng × tối đa 2 trang | 2 / 3,2,2,3 / 3 | 4 small |
| C1, C2 | Cùng source, config được chọn | 4 thành phố × tối đa 5 trang | 2 / được chọn / 3 | 2 full candidate |

Ngân sách mặc định: **4 full attempts tổng cộng**, cộng 2 smoke và 4 small attempts. Với mốc lịch sử 2.722 giây/lượt, riêng full khoảng 3 giờ; chưa bao gồm code/tests/small runs. Run lỗi vẫn tính ngân sách, không retry tự động để chọn mẫu đẹp. Dừng series khi có lỗi contract/completeness cần sửa; muốn chạy thêm hoặc đổi source sau baseline phải báo ngân sách và thiết lập lại phép so sánh trước khi tiếp tục, không ghép số liệu khác source tùy tiện.

Một cấu hình ABBA chỉ đủ điều kiện khi cả hai lượt của nó có ≥1 public record, mọi job complete, không duplicate page được chấp nhận, discard≤10%, đủ provenance và CPU/RAM samples. So median throughput của cấu hình hợp lệ; hòa giữ per-job=3. Các metric detail failure và coverage luôn được báo; kiểm chứng full là quyết định cuối.

### 10. Nghiệm thu và quyết định mặc định

Với `T0=median(R1.throughput,R2.throughput)`, chỉ xác nhận cải thiện khi `median(C1,C2)>T0`, `C1>T0` và `C2>T0`; không làm tròn trước so sánh, không đặt mức tăng phần trăm tối thiểu. Báo từng lượt, median/min/max, batch wall, số records/pages từng destination, listing/detail work, retry, slot wait, membership, optional coverage và CPU/RAM.

Mỗi full run phải ≥1 public record; required fields/giá VND đúng, discard≤10%; toàn bộ job thu đủ phạm vi hoặc có EOF xác nhận và page complete. Benchmark không đổi optional warning policy của pipeline. Trước quyết định mặc định, median coverage từng optional field không thấp hơn baseline, median tỷ lệ `detail_failures/detail_attempts` không cao hơn baseline (mẫu số 0 báo N/A; không suy ra cải thiện lỗi); không có OOM/crash hoặc vi phạm global cap. Sản lượng public giảm phải được đối chiếu số cards/EOF/membership từng destination; không chấp nhận giảm do logic bỏ dữ liệu. Biến động live chưa giải thích được thì báo chưa xác nhận và giữ mặc định.

Chỉ hai full candidate trên một máy/một ngày lưu trú là bằng chứng cải thiện quan sát được, không chứng minh ý nghĩa thống kê. Không đạt hoặc thiếu evidence là kết quả hợp lệ của thí nghiệm; không thêm heuristic/chạy thêm âm thầm để ép đạt.

Mặc định code hiện có per-job=2 và workers=3; profile benchmark 2/3/3 không phải fallback code. Nếu chọn per-job=2 thì không cần sửa constant đã là 2; cập nhật hướng dẫn profile sau xác nhận. Nếu chọn 3 và đủ bằng chứng, chỉ cập nhật constant detail tương ứng, CLI/default tests và docs cùng nhau. Không đổi fallback workers hoặc `.env` của người dùng trong change này.

## Risks / Trade-offs

- Correctness mới có thể phát hiện time/max exhaustion vốn bị báo complete → giữ partial, điều tra bằng metrics; không nới rule để lấy baseline thành công.
- Card thiếu mọi strong identity không thể được cứu chỉ bằng embedded trùng tên → giữ partial/diagnostics và báo sản lượng, không đoán identity.
- Đổi cách truyền metrics làm tăng phạm vi code/test → chỉ mapping trên result sẵn có, không đổi public JSONL hoặc consumer logic.
- Overhead metrics/provenance/sampler → giữ giống nhau ở baseline/candidate, đo một lần provenance/run, không làm tròn từng thao tác; counters bounded.
- Global semaphore giữ cả worker có thể làm per-job=2 nhanh hơn 3 tùy thứ tự job → dùng ABBA và full profile; chưa thay scheduling.
- Site/network/giá thay đổi giữa các lượt → cố định stay/profile, giữ toàn bộ mẫu, báo biến động/yield và giới hạn suy luận.
- Điểm lỗi browser/context/page hoặc retry có thể làm mất metrics → regression fault injection, counters trong finally và giữ release/cleanup tests.

## Migration Plan

Chỉ apply local crawler/tests/docs sau yêu cầu triển khai. Không migrate JSONL, Unity Catalog hay Airflow. Giữ metrics/page summaries mới là additive; test fixture complete cũ vẫn được chấp nhận và incomplete không được chấp nhận nhờ metadata mới.

Verification cuối dùng venv đã kiểm tra và lệnh trong [tasks.md](tasks.md); báo lỗi có sẵn/dependency thiếu/skips riêng, không tự cài hoặc sửa ngoài phạm vi. Review diff và links trước bàn giao; chưa archive khi còn thiếu verification đã yêu cầu.

Rollback theo diff/commit riêng của package đã apply, không reset hoặc đụng thay đổi người dùng; dùng run identity mới nếu crawl lại. Giữ baseline/candidate artifacts làm bằng chứng, không sửa output cũ. Nếu tối ưu không có lợi, giữ correctness/metrics đã xác minh và giữ nguyên mặc định; phần tối ưu nào giữ lại phải được báo rõ trong handoff.
