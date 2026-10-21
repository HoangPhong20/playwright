# Tasks

> **For agentic workers:** Khi được yêu cầu apply, đọc `openspec-apply-change` và thực hiện từng package theo design; dùng workflow thực thi phù hợp, TDD và verification. Code được giao tuần tự cho `gpt-6-luna`/`xhigh` theo AGENTS.md khi hỗ trợ; review trước khi chuyển package. Không triển khai trong lượt tạo plan.

**Goal:** Tăng số public records hợp lệ/phút trên full profile với cùng correctness contract và xác nhận bằng hai full candidate.

**Architecture:** Giữ Playwright Sync, browser reuse, per-job/global semaphore và merge hiện có. Metrics truyền qua page/job results; correctness hoàn tất trước baseline; tối ưu detail/payload thực hiện sau baseline.

**Tech Stack:** Python, Playwright/Chromium, pytest, PowerShell, OpenSpec; không thêm dependency runtime.

**Spec:** [Yêu cầu](specs/crawler-throughput/spec.md), [thiết kế](design.md). Đây là checklist thực thi duy nhất.

## Global Constraints

- Scope local crawler/tests/docs; Airflow/Databricks chỉ local compatibility tests, không deploy hoặc trigger live.
- Giữ required public fields, giá VND, optional warning policy, identity/propertyId và merge không ghi đè.
- Giữ timeouts, retry limits, full snapshot interval và wait/scroll settings; time cap vẫn có record floor hiện tại.
- Profile benchmark dùng CLI tường minh; mỗi run identity mới; không sửa output attempt cũ.
- Tổng ngân sách 4 full attempts, 2 smoke và 4 small; run lỗi vẫn tính ngân sách, không tự thay mẫu.
- Mỗi checkbox code phải có test tái hiện lỗi trước sửa, focused test đạt sau sửa và diff review; cập nhật trạng thái/evidence tại đây khi apply.
- Lệnh test bên dưới dùng PowerShell tại repository root và `venv/Scripts/python.exe` đã xác minh. Không tự cài dependency hoặc sửa lỗi ngoài phạm vi.

## Review Focus

Năm điều kiện đã đưa vào regression của package tương ứng: partial rời DOM trước embedded (3.1); quay lại trang cũ không liền kề (4.1); full snapshot cuối thêm field ngay lúc hết budget (5.1); timeout=0 thành chờ vô hạn và retry counter mất khi exception (7.2); classifier chỉ có bằng chứng ở attribute HTML (8.1).

## 1. Chuẩn bị execution và metrics listing

**Files:** `agoda_crawler/listing/{collection,page_crawl}.py`, `utils/crawl_metrics.py`, `tests/{test_listing_collection,test_page_crawl}.py`, `docs/RUNBOOK.md`.

- [x] 1.1 Kiểm tra lại `git status --short --branch`, `git worktree list`, HEAD, AGENTS và artifacts; xác minh `venv/Scripts/python.exe` bằng `-B -c "import sys; print(sys.executable)"`; ghi bằng chứng source/pre-existing changes và model routing thực tế tại checklist, không đưa thay đổi ngoài scope vào package. **Evidence (2026-10-20):** branch `update`; worktree duy nhất `D:/DE/databrick/playwright`; HEAD `0e700e522c8e71851d3d964e844cd1c98ab97691`; working tree sạch trước change, plan OpenSpec là thay đổi duy nhất hiện tại; root AGENTS và nested Airflow/Databricks instructions đã đọc; `venv/Scripts/python.exe` tồn tại và trả đúng absolute interpreter path. Model phiên chính giữ nguyên để điều phối. Runtime hỗ trợ cấu hình subagent riêng theo model và reasoning effort; task code được giao tuần tự cho `gpt-6-luna` với `max`, là effort cao nhất runtime liệt kê cho model Luna (không có lựa chọn `xhigh`).
- [x] 1.2 Thêm fake clock/snapshot tests cho regular/full counts, DOM/embedded/parse/merge/wait tách biệt và độ chính xác dưới 0,01s; thấy test fail rồi thêm timings/counters vào `ListingCollectionMetrics`/`PageCrawlResult.work_metrics` theo design §5; chạy focused `tests/test_listing_collection.py tests/test_page_crawl.py` và xác nhận không cộng trùng snapshot trong wait. **Evidence (2026-10-20):** regression tests đỏ trước implementation do thiếu snapshot counters và `PageCrawlResult.work_metrics`; sau implementation `23 passed` với `& '.\venv\Scripts\python.exe' -B -m pytest -p no:cacheprovider tests/test_listing_collection.py tests/test_page_crawl.py`; targeted Ruff và `git diff --check` đều đạt. Fake clock kiểm tra các phase riêng biệt dưới 0,01s và xác nhận snapshot work không bị cộng vào active wait.
- [x] 1.3 Thêm test hai page results có vòng cuộn khác nhau, kể cả page rỗng/probe/rejected attempt; bổ sung total/max/actions và đường aggregate; focused page tests phải chứng minh tổng vòng khác max và chi phí rejected attempt không biến mất. **Evidence (2026-10-20):** RED do thiếu `aggregate_scroll_metrics`, sau đó do outcome thiếu `scroll_rounds_total`; GREEN focused `tests/test_page_crawl.py tests/test_crawler.py tests/test_pagination.py`: `29 passed`. Tổng hợp gồm page rỗng, full attempt bị từ chối và probe action; summary accepted pages giữ nghĩa cũ. Targeted Ruff đạt.
- [x] 1.4 Ghi định nghĩa units/scope metrics và wall-vs-work sums vào runbook; review diff cùng test evidence, bảo đảm metrics chưa đổi quy tắc candidates, stop hoặc tốc độ chờ. **Evidence (2026-10-20):** đã bổ sung bảng định nghĩa trong `docs/RUNBOOK.md`; review độc lập bởi `gpt-6.1-sol/high` không có actionable findings cho tasks 1.2–1.4; root kiểm tra diff và xác nhận chỉ thêm instrumentation/aggregation, không đổi candidates, stop hay lịch snapshot/wait.

**Package 1 verification (2026-10-20):** root chạy full pytest bằng interpreter venv: `202 passed, 2 skipped`; hai module `test_databricks_retry.py` và `test_databricks_spark.py` skip do thiếu PySpark, không tự cài dependency. Ruff trên bảy file Python đã sửa đạt; Ruff toàn repository còn 32 lỗi có sẵn trong `extraction/fields.py`, `airflow/scripts/validate_latest_run.py` và Databricks wrapper notebooks không thay đổi. Mypy còn 8 lỗi có sẵn trong 6 file; các lỗi ở `collection.py` và `crawl_metrics.py` thuộc các hàm không thay đổi. `git diff --check` và strict OpenSpec validation đạt. Chưa chạy live crawler hoặc benchmark; chưa có bằng chứng tăng throughput.

## 2. Metrics detail, job/batch và provenance

**Files:** `agoda_crawler/enrichment/detail.py`, `crawler.py`, `jobs.py`, `orchestration.py`, `utils/{crawl_metrics,run_output}.py`, `tests/{test_detail_resources,test_utils,test_orchestration_output}.py`, `docs/RUNBOOK.md`.

**Interfaces:** `CrawlJobResult.metrics`, optional `metrics_outcome` của hai crawler APIs/enrichment, `jobs[].metrics`, `stays[].metrics`, manifest `summary`; keys theo design §5. Không đổi list records trả về của crawler.

- [x] 2.1 Thêm fake semaphore/clock tests cho acquire serial một lần trên nhiều records và parallel từng worker, bao gồm lỗi browser/context/page; sau red-green, slot count/wait đúng một lần acquire và `tests/test_detail_resources.py` vẫn bảo vệ global cap/cleanup. **Evidence (2026-10-20):** RED `8 failed, 13 passed` do API thiếu `metrics_outcome`; GREEN và root xác minh `22 passed`. Kiểm tra serial 5 records/1 acquire, parallel 2 workers/2 acquires, không semaphore/0, và fault paths. Targeted Ruff, diff-check đạt; review độc lập `gpt-6.1-sol/high` không có actionable findings.
- [x] 2.2 Thêm tests detail attempt fail/discard/empty job và retry bị exception; đếm selected/scheduled/attempted/failed/retries/missing-target đúng định nghĩa, thời gian lỗi vẫn giữ; focused detail/output tests đạt và số liệu legacy không đổi nghĩa. **Evidence (2026-10-20):** RED 4 regressions serial/empty/discardable/retry (`4 failed, 22 passed`) và một regression qua real parallel worker (`1 failed, 26 deselected`) trước sửa; GREEN/root xác minh detail `27 passed`, utils/output `19 passed`; targeted Ruff đạt. Timing giữ độ chính xác cho goto/extraction thất bại; retry tăng trước work; legacy status/timing/retry metadata giữ nghĩa cũ. Review độc lập `gpt-6.1-sol/high` không có actionable findings.
- [x] 2.3 Thêm result metrics và truyền mapping độc lập mỗi job vào manifest/log; fake concurrent jobs và job không có public records phải chứng minh totals không dựa vào public records hoặc chia sẻ accumulator giữa jobs; kiểm tra `batch_wall_seconds` từ perf counter theo ranh giới design, không dùng sum job times. **Evidence (2026-10-20):** các slice mapping/crawler/probe/log/manifest/batch đều có RED trước sửa; review bổ sung regressions cho mất metrics khi pagination/probe/launch/output/worker lỗi, gồm first-snapshot failure và JSONL writer failure sau khi worker hoàn tất. Metrics giữ qua `finally`, checkpoint job trước ghi JSONL; execution failure boundary dừng trước complete-manifest/pointer. Đồng hồ giả xác nhận batch 1,4s độc lập job wall sum 300s, loại 10s/20s publication. Affected suite `98 passed`; root full pytest `225 passed, 2 skipped` (thiếu PySpark), targeted Ruff và diff-check đạt. Review độc lập `gpt-6.1-sol/high` xác nhận không còn actionable findings; JSONL projection và các chỉ số legacy giữ nguyên.
- [x] 2.4 Bổ sung provenance an toàn gồm source SHA-256, dirty/diff/untracked source fingerprints, resolved AGODA whitelist/constants và versions; test với fake Git/config chứng minh không log secret/full environment, config thay đổi được phát hiện và file hash có thứ tự ổn định. **Evidence (2026-10-20):** provenance được chụp một lần/attempt, allowlist CLI/config không xuất environment hoặc raw diff; source hashes có thứ tự ổn định, Chromium versions lấy từ browser hiện có dưới lock. Regression RED/GREEN bảo vệ secret, phạm vi fingerprint, nhiều browser và cleanup khi metadata lỗi. Review phát hiện staged deletion thiếu trong diff hash; ba regression fake Git RED trước sửa, GREEN sau hợp HEAD/index paths, giữ index-only để nhận diện untracked và không gọi diff không giới hạn khi tập paths rỗng. Focused provenance/orchestration `23 passed`; root full `236 passed, 2 skipped`; targeted Ruff đạt. Review độc lập `gpt-6.1-sol/high` xác nhận finding đã giải quyết, không có actionable regressions.
- [x] 2.5 Thêm hướng dẫn capture CPU/RAM cây Python/Chromium chu kỳ 5s và bảng artifacts benchmark trong runbook; review snippet PowerShell, đường output ignored và vòng đời sampler, không chạy crawler để kiểm tra ở bước chỉ sửa docs. **Evidence (2026-10-20):** thêm section sampler và bảng artifacts trong `docs/RUNBOOK.md`; PowerShell `Parser.ParseInput` xác nhận snippet không có syntax errors; `git check-ignore data/benchmarks/syntax-check.resources.jsonl` xác nhận output ignored. Review độc lập `gpt-6.1-sol/high` không có actionable findings. Chưa chạy sampler/crawler; live coverage/overhead cần bằng chứng ở benchmark.
- [x] 2.6 Review package metrics với focused `tests/test_detail_resources.py tests/test_utils.py tests/test_orchestration_output.py`; xác nhận public JSONL projection không có metrics và mọi counter vẫn có khi publishable=0. **Evidence (2026-10-20):** affected tests của 2.3 và full suite mới nhất bảo vệ projection business-only, job rỗng/discarded, fault paths và aggregation độc lập với public records. Root full pytest `236 passed, 2 skipped` (thiếu PySpark), targeted Ruff đạt; full Ruff vẫn 32 lỗi có sẵn ngoài thay đổi, mypy vẫn 8 lỗi đã ghi ở package 1. Review độc lập metrics và provenance không còn actionable findings. Không chạy crawler live, chưa kết luận tăng throughput.

**Re-audit theo yêu cầu người dùng (2026-10-20, hoàn tất):** người dùng cho phép cài dependency optional; `pyspark==4.0.1` và `py4j==0.10.9.9` đã cài vào `venv`, `pip check` đạt, Java 21.0.9 có sẵn. Không thay dependency runtime hoặc cấu hình hệ thống. Root chạy lại full pytest sau các bản sửa: **`264 passed`, không skip, 100,84s**, gồm 7 test Spark local thực và 5 test retry bằng fake. Trước sửa, full suite đạt 256 test nhưng chưa bao phủ các fault paths mới. Agent kiểm tra affected suite `74 passed`; root xác minh riêng page/crawler `34 passed` và orchestration `17 passed` trong quá trình sửa, sau đó full suite nêu trên xác nhận source cuối. Targeted Ruff cho code/tests gói 1–2 đạt; full Ruff vẫn 32 lỗi có sẵn (3 unused imports trong `extraction/fields.py`, 1 trong Airflow validator, 28 ở notebook wrappers), mypy vẫn 8 lỗi có sẵn trong 6 file, không phát sinh lỗi mới. Syntax sampler PowerShell và ignored output đạt. Strict OpenSpec và diff-check được kiểm tra lại sau cập nhật bằng chứng.

Review độc lập bởi `gpt-6.1-sol/high` ban đầu phát hiện hai gap quan trọng trong 2.3 và một gap timing nhỏ từ phần gói 3 đang làm dở. Các bản sửa do `gpt-6-luna/max` thực hiện tuần tự, mỗi regression đều RED trước sửa và GREEN sau sửa: page/wait giữ work metrics qua lỗi ở vòng sau và snapshot cuối; summary vòng cuộn được giữ trước khi capture pagination có thể lỗi; worker kết xuất kết quả qua out-channel, thu đủ futures trước khi ném lại lỗi đầu, checkpoint manifest theo identity job; lỗi annotation/print vẫn giữ metrics của job hiện tại với trạng thái failed; lỗi cleanup không thay lỗi gốc; seed merges được tính trong `merge_seconds`. Review cuối xác nhận không còn actionable findings cho mười task đã check. 2.3/2.6 đã mở lại trong re-audit và chỉ check lại sau test/review. Gói 3 vẫn partial, không task 3.x nào được nghiệm thu; không chạy crawler live, benchmark hoặc workspace Airflow/Databricks.

| Task | Kết quả re-audit | Bằng chứng chính |
| --- | --- | --- |
| 1.1 | Đạt | Branch/worktree/HEAD và absolute interpreter xác minh lại; model routing thực tế giữ bằng chứng lịch sử trong task. |
| 1.2 | Đạt sau sửa timing seed | Fake-clock snapshot/page tests, `test_observed_record_seed_merge_is_counted_as_merge_time`; không cộng snapshot vào wait. |
| 1.3 | Đạt | Page/probe/rejected/empty totals và max; thêm regression lỗi capture trang đầu để giữ rounds/actions. |
| 1.4 | Đạt | Review định nghĩa units, wall/work, DOM call và lịch snapshot/wait trong runbook. |
| 2.1 | Đạt | Serial/parallel acquire-count, fault cleanup và global-cap tests trong `test_detail_resources.py`. |
| 2.2 | Đạt | Candidates/scheduled/attempts/retry-before-work, failed/discarded/empty timing tests. |
| 2.3 | Đạt sau sửa fault retention | `test_failed_page_crawl_publishes_partial_metrics_after_round_failure`, final-snapshot/capture lỗi; serial close, concurrent launch và current-job processing failures trong `test_orchestration_output.py`. |
| 2.4 | Đạt | `test_provenance.py`: allowlists, deterministic hashes, HEAD/index deletion, empty-path guard, unavailable states và Chromium observations. |
| 2.5 | Đạt trong phạm vi static | Sampler snippet parse đạt, output ignored; live accuracy/overhead vẫn thuộc benchmark sau này. |
| 2.6 | Đạt sau review lại | JSONL projection/zero-public giữ coverage; full 264 test đạt, reviewer không còn finding cho gói 1–2. |

## 3. Membership embedded và fallback trước baseline

**Files:** `agoda_crawler/listing/{collection,page_crawl,records}.py`, `extraction/{fields,selectors}.py`, `utils/debug_artifacts.py`, `tests/{test_listing_collection,test_listing_records,test_page_crawl,test_extraction,test_debug_artifacts}.py`, `docs/DATA_QUALITY.md`. `records.py` giữ nguyên; chỉ xác minh tests hiện có. Selectors và writer dùng chung là phần hỗ trợ trực tiếp cho membership/diagnostics của gói này.

**Interfaces:** `collect_listing_snapshot(..., *, observed_records: List[Dict] | None = None)`; reuse canonical/property helpers, không thêm dedupe index.

**Execution gói 3 (2026-10-21, hoàn tất trong phạm vi local):** người dùng phê duyệt riêng tasks 3.1–3.4. Worker `/root/package3_worker` được tạo bằng `gpt-6-luna`/`xhigh`; công cụ chấp nhận lựa chọn này. Giữ checkout `update` tại HEAD `0e700e522c8e71851d3d964e844cd1c98ab97691` và toàn bộ thay đổi có sẵn; bản chụp đầu lượt trong ignored `debug/codex-package3-1dfa9908e7/` dùng để tách diff gói 3 khỏi gói 1–2. Baseline mới chạy trước sửa đạt **264 passed, 119,38s, exit 0**, gồm Spark local; Ruff có 32 lỗi và mypy có 8 lỗi trong 6 file. Audit và review tái sử dụng core behavior/tests 3.1–3.2, không triển khai lại các phần đã có.

**Review gói 3 (đã nghiệm thu):** reviewer `/root/package3_review` (`gpt-6.1-sol`/`high`) tìm thấy R1 trong code có sẵn: DOM scan và fallback broad selector nhận footer/recommendation làm card gốc. Re-review tiếp tục tái hiện module ngoài vùng listing và excluded subtree nằm trong wrapper hợp lệ, có thể trộn URL/property ID/giá/tên. Mọi sửa code do cùng worker Luna thực hiện; regression RED trước sửa rồi GREEN, gồm hai raw name reads còn sót ở vòng cuối. Reviewer tự chạy lại repro Chromium local và kết luận **R1/P2 ADDRESSED, không còn actionable finding trong gói 3**. Không dùng số test đạt của bản trước sửa làm bằng chứng source cuối.

**Quyết định triển khai và ranh giới:** dùng chung bằng chứng strict card/root giữa collection và fallback; broad cards chỉ tạo membership trong vùng search-results/main hợp lệ, generic div anchor chỉ bổ sung identity đã quan sát. Giữ broad-only fallback trong semantic main/search-results; không lọc theo heading, quảng cáo hay địa giới. Đọc dữ liệu từ eligible subtree, bỏ text ẩn; filter chỉ bật cho listing, không đổi hành vi detail mặc định. DOM không có strict card và cũng không xác định được vùng listing là markup chưa được hỗ trợ; cần bằng chứng trước khi nới fallback. Quyết định này ưu tiên không tự tạo record ngoài listing; rủi ro là giảm recall với markup chưa nhận diện. Chưa có bằng chứng DOM Agoda live hoặc cải thiện throughput.

- [x] 3.1 Thêm red tests cho embedded-only không tạo record, card snapshot trước rời DOM rồi embedded khớp propertyId bổ sung URL, embedded trước card không tự tạo membership; sửa snapshot/page plumbing và cập nhật test embedded cũ đang kỳ vọng record dù DOM rỗng; focused collection/page tests đạt. **Evidence (2026-10-21):** giữ các regression có sẵn `test_collect_listing_snapshot_does_not_admit_embedded_only_urls`, `test_later_embedded_snapshot_enriches_card_observed_before_virtualization`, `test_unmatched_embedded_url_is_not_cached_for_a_later_partial_card` và page plumbing test. Đã xác minh trên focused/full suite source cuối; review xác nhận embedded không tạo root mới sau sửa R1. Không ghi nhận RED mới cho phần core đã có trước lượt này.
- [x] 3.2 Thêm tests trùng tên/city suffix không đủ match, conflicting IDs không ghép, same-path/different-ID tách biệt, partial/full merge hai chiều và card lân cận thật được giữ; chỉ sửa helper hiện có khi cần và chạy `tests/test_listing_records.py tests/test_listing_collection.py` đạt. **Evidence (2026-10-21):** tái sử dụng tests strong identity/name-conflict, same-path/property ID khác nhau, partial/full 44 properties hai chiều và neighboring-city card. Không sửa `records.py` hoặc thêm dedupe index; focused/full suite đạt, reviewer không có finding cho identity contract.
- [x] 3.3 Thêm fake fallback/probe có link recommendation/footer cùng hotel card hợp lệ; giới hạn đường `extract_page_results`/hotel-links theo membership/card container, truyền observed records khi cần; collection/extraction/page tests chứng minh không có đường vòng tạo nonmember. **Evidence (2026-10-21):** thêm probe regression và Chromium local `page.set_content` tests cho footer div/article/li, recommendation, recently-viewed/also-like ngoài root, generic div, broad-only main/search-results, wrapper chỉ có excluded links, mixed card và recommendation text trong anchor. RED ghi nhận 3 collection + 1 fallback failures ban đầu, tiếp theo 2 collection + 1 fallback root failures, wrapper failures riêng từng route và hai name failures trước sửa cuối; mọi trường hợp đều GREEN sau sửa. Các positive cases giữ strict/broad card thật, sponsored result, observed identity và visible price. Filter/helpers chỉ dùng cho listing; review cuối đóng R1/P2.
- [x] 3.4 Thêm test counts seen/unique/unmatched và bounded samples 25 URL/trang, ≤500 ký tự/URL; lưu diagnostics trong batch/destination/check-in; cập nhật DATA_QUALITY về nguồn membership và review diff không lọc khách sạn chỉ bằng địa giới. **Evidence (2026-10-21):** RED ban đầu 4 failed/14 passed do thiếu counters/writer; GREEN bảo vệ exact counts >25, canonical/tracking aliases, reset mỗi crawl, late-card/fallback resolution, probe và writer errors không che lỗi gốc. Writer test xác minh hai run/destination contexts không ghi đè, sample ≤25 và URL ≤500 ký tự. Counters đi qua `page_scroll_summaries` tới manifest; không đưa URL samples vào public JSONL hoặc gán page-unique thành unique toàn batch. Cập nhật `docs/DATA_QUALITY.md`; reviewer xác nhận phạm vi local đạt.

**Verification source cuối của gói 3 (2026-10-21):** worker chạy focused bằng `venv/Scripts/python.exe -B -m pytest -p no:cacheprovider -x tests/test_listing_collection.py tests/test_listing_records.py tests/test_page_crawl.py tests/test_extraction.py tests/test_debug_artifacts.py`: **91 passed, 78,12s**. Lead chạy full `venv/Scripts/python.exe -B -m pytest -p no:cacheprovider`: **290 passed, không skip, 214,58s, exit 0**, gồm Spark local và Chromium local không network. Windows vẫn in `ERROR: Access denied` sau pytest summary như baseline; chưa xác định nguồn dòng này, không có pytest failure. Lead chạy full Ruff (`--no-cache --output-format json`): vẫn 32 lỗi baseline, so filename/code/message không có lỗi mới; targeted Ruff của các file thay đổi ngoài ba imports lỗi cũ ở `fields.py` đạt. Full mypy (`--cache-dir=nul`) vẫn 8 lỗi baseline trong 6 file, không có lỗi mới. Không sửa lỗi lint/type ngoài phạm vi, không cài dependency, chạy live crawler/benchmark hoặc deploy/trigger Airflow/Databricks; chưa archive. Báo cáo worker và diff tách từ bản chụp đầu lượt nằm trong ignored `debug/codex-package3-1dfa9908e7/`. Bước tiếp theo là gói 4; toàn change chưa hoàn tất.

**Kiểm tra artifacts cuối:** `openspec.cmd validate improve-crawler-throughput --strict --no-interactive` và `git diff --check` đạt sau cập nhật bằng chứng/nghiệm thu. OpenSpec xác nhận **14/41 task hoàn thành, còn 27**; tasks 4–10 giữ nguyên trạng thái chưa hoàn thành. Đã review diff tài liệu và các tham chiếu tới design/specs hiện có.

## 4. Novelty pagination

**Files:** `agoda_crawler/listing/pagination.py`, `crawler.py`, `tests/{test_pagination,test_crawler}.py`, `docs/DATA_QUALITY.md`.

**Interfaces:** `pagination_change_evidence(previous, current, *, seen_identities: set[str] | None = None) -> Dict` theo design §4.

- [ ] 4.1 Thêm red tests reorder, subset, tracking-only, page1→page2→page1; sửa predicate novelty cùng ngưỡng hai tín hiệu hiện có; `tests/test_pagination.py` phải từ chối mọi case không có identity mới dù có URL/active-page/scroll signals.
- [ ] 4.2 Truyền accepted identities qua cả probe/full collection, chỉ cập nhật sau accept; tests phải chấp nhận new identity+đủ signals, giữ propertyId khác nhau trên shared path, không pollute accepted set từ probe/rejected page và giữ navigation retries/EOF.
- [ ] 4.3 Cập nhật DATA_QUALITY về novelty/EOF; chạy focused pagination/crawler/navigation tests và review diff, không thay selectors điều hướng hoặc tăng retry budget ngoài scope.

## 5. Stop reasons, completeness và compatibility manifest

**Files:** `agoda_crawler/listing/page_crawl.py`, `crawler.py`, `orchestration.py`, `utils/debug_artifacts.py`, `tests/{test_page_crawl,test_crawler,test_orchestration_output,test_airflow_validate_latest_run,test_databricks_pipeline}.py`, `docs/{DATA_QUALITY,RUNBOOK}.md`. `run_manifest.py` và `databricks/agoda_etl/utils.py` chỉ đọc đối chiếu.

- [ ] 5.1 Thêm red tests cho bốn stop reasons, stable/exhausted ưu tiên khi đồng thời hết budget, final full snapshot thêm identity/field đúng lúc cap/max; thêm `PageCrawlResult.stop_reason` và quyết định theo bảng design §3; focused tests chứng minh reset stability, không full-snapshot loop vô hạn và giữ time-cap minimum record test cũ.
- [ ] 5.2 Propagate incomplete từ cả trang đầu và candidate page, giữ partial records/diagnostics, bỏ enrichment trên job incomplete; test max_pages=1 và EOF không che page thu dở, pages_collected chỉ gồm trang hoàn tất, mọi partial page có summary.
- [ ] 5.3 Thêm orchestration tests batch failed/no new completion pointer với job incomplete, cả fresh batch và retry sau complete attempt cũ; giữ output bất biến và pointer cũ nguyên trạng; `tests/test_orchestration_output.py tests/test_run_context.py` đạt.
- [ ] 5.4 Thêm local manifest fixtures complete cũ, complete+metrics/page reasons mới và incomplete; `tests/test_airflow_validate_latest_run.py tests/test_databricks_pipeline.py` phải chấp nhận hai complete fixtures và từ chối incomplete, không sửa/nới consumer production hoặc chạy live workspace.
- [ ] 5.5 Cập nhật DATA_QUALITY/RUNBOOK về page-vs-job reason, record-floor time cap và partial diagnostics; review toàn bộ correctness diff và source/test compatibility trước thu baseline.

## 6. Khóa profile, smoke và hai baseline

**Files/artifacts:** `docs/RUNBOOK.md`, `data/benchmarks/<series-id>/`, run output/debug ignored; không sửa throughput logic trong package này.

- [ ] 6.1 Chạy full pytest/Ruff/mypy bằng lệnh §10 trước live baseline; ghi failures/skips/dependency thiếu riêng. Chốt một check-in tương lai, CLI profile design §8, source fingerprint, effective config và sampler; kiểm tra bảng settings không chứa secret và ghi ngày một lần cho cả series.
- [ ] 6.2 Khi live validation đã được cho phép ở bước apply, chạy S0 Vũng Tàu/1 trang/1 worker/no detail với identity mới; kiểm tra page stop, completeness, required fields, membership diagnostics, metrics và pointer trước khi mở rộng; không chỉ dựa vào exit code.
- [ ] 6.3 Chạy R1 rồi R2, cùng source/config workers=2/per-job=3/global=3 và full profile; mỗi lượt lưu provenance, logs, manifest, counters, CPU/RAM và aggregate JSONL validation; ghi cả run lỗi vào bảng, không tự chạy thay thế.
- [ ] 6.4 Tính throughput/batch wall/median baseline không round sớm; chứng minh mỗi job đủ page hoặc EOF, discard≤10%, public≥1, xác định chi phí listing/detail chính và review hai baseline đủ điều kiện trước tối ưu; không đủ thì dừng series và báo evidence/budget còn lại.

## 7. Tối ưu detail extraction sau baseline

**Files:** `agoda_crawler/extraction/{fields,selectors,__init__}.py`, `enrichment/detail.py`, `tests/{test_extraction,test_crawler,test_detail_resources}.py`, `docs/RUNBOOK.md`.

**Interfaces:** `extract_detail_fields(page, *, fields: tuple[str, ...] | None = None) -> Dict[str, Optional[str]]`; `None` toàn bộ keys cũ, tuple đúng keys yêu cầu, `()` không DOM; callers retry truyền missing tuple.

- [ ] 7.1 Thêm red extraction tests cho None/selected/empty/unknown fields, selector text `8.6` parse không đủ nhưng body có rating/review, selector đủ không đọc body và nhiều missing chỉ đọc body một lần; triển khai field parsing/fallback và selectors chung, `tests/test_extraction.py` đạt cùng giá VND/parser regressions cũ.
- [ ] 7.2 Thêm retry tests lấy giá lần đầu, chỉ rating/review ở retry, target tuple rỗng, timeout≤0 trả ngay, selector sau có sẵn và lỗi trong retry vẫn tăng counter; dùng locator nhóm một wait, giữ retry/timeout config; `tests/test_crawler.py` và extraction tests đạt, không DOM reads cho field không yêu cầu.
- [ ] 7.3 Test merge không ghi đè giá/rating có sẵn và một detail lỗi không dừng queue; chạy `tests/test_detail_resources.py` với fault/global cap tests, cập nhật runbook mô tả phạm vi extraction và review counters cho mọi candidates kể cả discard; không đổi nhãn success.

## 8. Tối ưu payload listing sau baseline

**Files:** `agoda_crawler/listing/collection.py`, `utils/debug_artifacts.py`, `tests/{test_listing_collection,test_page_crawl}.py`, `docs/RUNBOOK.md`.

- [ ] 8.1 Thêm regression carousel/filter chỉ có dấu hiệu trong attribute HTML và card thật tương tự; đưa bằng chứng lọc sang cờ DOM nhỏ trước khi bỏ preview, sau red-green classifier phải giữ cùng quyết định khi không có `outerHtmlPreview`.
- [ ] 8.2 Tạo preview có điều kiện cho partial/invalid/debug, bảo thủ với URL chưa normalize; test/fake DOM có bộ đếm chứng minh card valid đầy đủ không gọi tạo outerHTML, partial/invalid có preview ≤1.000 ký tự và bounded samples; review không thêm scan toàn DOM hoặc cache mới.
- [ ] 8.3 Test URL/giá xuất hiện muộn, cards bị virtualize, full interval và final confirmation vẫn merge; chạy collection/page tests đạt, cập nhật runbook counters payload và review diff xác nhận không đổi wait/scroll/snapshot schedule ngoài correctness đã khóa ở baseline.

## 9. Smoke candidate, ABBA và hai full candidate

**Files/artifacts:** `docs/RUNBOOK.md`, `data/benchmarks/<series-id>/` và outputs ignored; profile/default decisions theo design §8–10.

- [ ] 9.1 Chạy lại full pytest/Ruff/mypy sau code changes, khóa candidate source/config và chạy S1 smoke cùng giới hạn S0; kiểm chứng manifest/public/membership/metrics/CPU-RAM đủ evidence trước ABBA, không dùng synthetic timing để kết luận speedup.
- [ ] 9.2 Chạy A1/B1/B2/A2 đúng thứ tự 3/2/2/3 trên Vũng Tàu+Đà Nẵng × 2 trang, workers=2/global=3; giữ source/date/settings còn lại, mỗi identity mới; lưu cả bốn run và xác định eligibility cả hai mẫu mỗi config theo design, không chọn riêng lượt đẹp.
- [ ] 9.3 Tính median throughput ABBA theo config hợp lệ, hòa giữ 3; ghi retry/failures/slot wait/coverage/CPU-RAM và lý do chọn; không config hợp lệ thì ghi chưa chọn và dừng full candidate thay vì tự tăng browser hay đổi scheduling.
- [ ] 9.4 Chạy C1 rồi C2 trên full profile với config được chọn, mỗi output mới, giữ candidate source; kiểm chứng mọi job/page, required fields, discard, coverage và provenance/sampler, không vượt tổng 4 full attempts.
- [ ] 9.5 So sánh mỗi C1/C2 với median R1/R2, cùng median throughput, batch/listing/detail wall-work, sản lượng từng city/EOF/membership, optional coverage, detail failure rate, retry/slot wait và CPU/RAM; ghi kết luận theo design §10 và mọi hạn chế live. Thiếu evidence hoặc giảm sản lượng chưa giải thích thì giữ mặc định.
- [ ] 9.6 Nếu full xác nhận lợi ích, cập nhật hướng dẫn profile trong runbook/README và chỉ sửa `config.py` constant detail nếu giá trị chọn khác fallback hiện tại; sửa tests CLI/defaults tại `tests/test_main.py` cùng lúc, chạy focused tests. Nếu không đạt hoặc constant đã bằng giá trị chọn, ghi rõ quyết định không sửa; không đổi workers fallback hay `.env` người dùng.

## 10. Integration verification và bàn giao

**Files:** toàn diff trong scope; checklist này giữ evidence thực tế, runbook giữ aggregate benchmark. Không tạo checklist thứ hai.

- [ ] 10.1 Sau thay đổi cuối, chạy full pytest, Ruff và mypy dưới đây; ghi chính xác counts/pass/fail/skips và dependency thiếu. Nếu đã có kết quả mới nhất trên source không đổi ở 9.1 và không sửa code sau đó, tái dùng evidence đó; không chạy lại chỉ để lặp báo cáo.
- [ ] 10.2 Chạy strict OpenSpec validation, review diff/links và đối chiếu từng requirement với test/benchmark; ghi coverage map và remaining gaps tại checklist, không đánh dấu benchmark hoàn tất bằng unit tests.
- [ ] 10.3 Bàn giao change summary, source/config fingerprints, bảng từng run+median, output paths và ranh giới local/fake/live; chứng minh không deploy/trigger Airflow/Databricks, không thêm gate discard hoặc sửa public schema. Chỉ archive theo workflow khi verification thực tế đủ và được yêu cầu.

```powershell
.\venv\Scripts\python.exe -B -m pytest -p no:cacheprovider
.\venv\Scripts\python.exe -m ruff check . --no-cache
.\venv\Scripts\python.exe -m mypy agoda_crawler --cache-dir=nul
openspec.cmd validate improve-crawler-throughput --strict --no-interactive
```

Focused tests dùng cùng interpreter và `-B -m pytest -p no:cacheprovider` với các file được chỉ rõ trong mỗi package. `openspec.cmd` là shim CLI trên Windows để không phụ thuộc execution policy của `openspec.ps1`.
