# Runbook

## Chuẩn bị

Chạy lệnh từ root repository:

```powershell
cd D:\DE\databrick\playwright
.\venv\Scripts\Activate.ps1
py -m pip install -r requirements-dev.txt
py -m playwright install
```

Mặc định `.env` chạy headless, outer workers là 2 và detail concurrency là 3.

## Run output and detail cap

Each unique `airflow_run_id` and `airflow_try_number` creates one immutable
attempt directory with a `run_manifest.json`. For a 2-worker/3-detail setup,
keep the global cap at 3:

```text
AGODA_TOTAL_DETAIL_CONCURRENCY=3
```

Use `--total-detail-concurrency` only when intentionally overriding that cap.

## Smoke test listing

Lệnh này không crawl detail nên nhanh và phù hợp để kiểm tra selector/pagination:

```powershell
$checkIn = (Get-Date).AddDays(21).ToString("yyyy-MM-dd")
$runId = "manual_$(Get-Date -Format 'yyyyMMdd_HHmmss_fffffff')"
py main.py --airflow-dag-id adhoc --airflow-run-id $runId `
  --airflow-try-number 1 --output-dir data/airflow `
  --destinations "Vung Tau" `
  --date $checkIn `
  --max-pages 1 --workers 1 --no-enrich-details
```

## Crawl có detail

Không thêm `--no-enrich-details` nếu muốn so sánh `detail-concurrency`:

```powershell
$checkIn = (Get-Date).AddDays(21).ToString("yyyy-MM-dd")
$runId = "manual_$(Get-Date -Format 'yyyyMMdd_HHmmss_fffffff')"
py main.py --airflow-dag-id adhoc --airflow-run-id $runId `
  --airflow-try-number 1 --output-dir data/airflow `
  --destinations "Vung Tau" `
  --date $checkIn `
  --max-pages 2
```

## Benchmark detail concurrency

Giữ nguyên city/date/max-pages và dùng run identity khác nhau:

```powershell
$checkIn = (Get-Date).AddDays(21).ToString("yyyy-MM-dd")
$runId = "manual_$(Get-Date -Format 'yyyyMMdd_HHmmss_fffffff')"
py main.py --airflow-dag-id adhoc --airflow-run-id "${runId}_detail_2" `
  --airflow-try-number 1 --output-dir data/airflow `
  --destinations "Vung Tau" `
  --date $checkIn `
  --max-pages 2 --detail-concurrency 2

py main.py --airflow-dag-id adhoc --airflow-run-id "${runId}_detail_3" `
  --airflow-try-number 1 --output-dir data/airflow `
  --destinations "Vung Tau" `
  --date $checkIn `
  --max-pages 2 --detail-concurrency 3
```

So sánh `seconds=...`, `detail_sum=...`, coverage và số record publishable. Không chọn cấu hình nhanh hơn nếu coverage thấp hơn hoặc có pagination duplicate.

## Đọc kết quả

- `pages=2/2 duplicate=0`: crawl đủ page yêu cầu và không phát hiện page lặp.
- `page_records`: số unique record trong từng page trước khi merge toàn run.
- `records`: số record publishable sau khi lọc thiếu trường bắt buộc.
- `timing`: `search_sum`, `listing_sum`, `detail_sum`; dùng để xác định bottleneck.
- `VERIFY_COVERAGE_STATUS=success`: không có record bị loại vì thiếu `hotel_name`, `hotel_url` hoặc `price_value`.
- `VERIFY_OPTIONAL_COVERAGE_STATUS`: `success` khi coverage của từng field rating/review/star lớn hơn `90%`; `warning` không làm job fail.
- `VERIFY_DISCARDED_RECORDS`: số record không được ghi vào JSONL public.

### Phạm vi metrics listing

Các thời gian thành phần dùng giây từ `perf_counter()`, giữ độ chính xác khi
cộng dồn và chỉ làm tròn khi hiển thị. Các bộ đếm lấy từ kết quả thu thập trang,
kể cả trang rỗng và lần thu thập bị từ chối; không suy ngược từ record public.

| Metric | Đơn vị và phạm vi |
| --- | --- |
| `regular_snapshot_count`, `full_snapshot_count` | Số snapshot; hai nhóm loại trừ nhau. Full dùng cả broad selectors và embedded scan. |
| `dom_call_seconds`, `embedded_call_seconds` | Wall time của lời gọi Playwright tương ứng, gồm evaluate và truyền kết quả; không phải thời gian CPU của JavaScript. |
| `parse_dedupe_seconds` | Thời gian xử lý Python để parse và chuẩn hóa/dedupe candidates, tách khỏi merge. |
| `merge_seconds` | Thời gian merge trong snapshot và merge snapshot vào tập record tích lũy của trang. |
| `active_wait_seconds` | Thời gian chờ chủ động và lazy waits. Snapshot chạy trong vòng chờ vẫn thuộc các phase snapshot, không cộng lần nữa vào wait. |
| `other_seconds` | Phần wall time còn lại của trang sau khi trừ các phase đã đo riêng. |
| `scroll_rounds_total`, `scroll_rounds_max` | Tổng và giá trị lớn nhất của số vòng thu thập từ các page results, gồm cả lần thu thập rỗng hoặc bị từ chối. |
| `scroll_actions` | Số lần scroll thực sự di chuyển, gồm cả probe; probe không tự tạo thêm vòng thu thập trang. |

Giữ `scroll_rounds` trong summary từng trang theo nghĩa cũ. Summary các trang
được chấp nhận và metrics của mọi lần thử có phạm vi khác nhau: một lần thử bị
từ chối vẫn tiêu tốn công việc dù không đóng góp record public.

Wall time đo khoảng thời gian thực của một trang/job/batch. Work time là thời
gian thành phần được cộng dồn; khi nhiều job chạy đồng thời, tổng work/job time
có thể lớn hơn batch wall time. Không cộng cả wall time của vòng chờ lẫn các
snapshot nằm trong vòng đó, và không dùng tổng work time thay cho batch wall
time khi tính throughput.

### Metrics detail và job/batch

Metrics mới theo toàn bộ ứng viên đi qua `jobs[].metrics`, rồi được tổng hợp
vào `stays[].metrics` và manifest `summary`. Mỗi job có mapping riêng, kể cả
khi không có record public. JSONL public vẫn chỉ chứa các business fields.

| Metric | Đơn vị và phạm vi |
| --- | --- |
| `search_wall_seconds`, `listing_wall_seconds`, `detail_wall_seconds`, `job_wall_seconds` | Giây theo từng phase/job; detail wall gồm cả thời gian chờ slot và vòng đời tài nguyên detail. |
| `batch_wall_seconds` | Giây từ trước chuẩn bị worker/browser đến sau ghi output và summary, trước publish complete manifest/pointer; không lấy tổng job times. |
| `detail_candidates`, `detail_scheduled` | Số ứng viên đủ điều kiện trước và sau giới hạn `max_detail_pages`. |
| `detail_attempts`, `detail_failures` | Attempts bắt đầu khi gọi `goto`; failures theo trạng thái cuối `failed` của các attempts, không theo việc có record public hay không. |
| `field_retries` | Số vòng retry đã bắt đầu; exception trong retry không xóa số lần đã thử. |
| `detail_missing_target_after_attempt` | Số attempts vẫn thiếu ít nhất một target field sau xử lý; không suy từ nhãn `success`. |
| `load_seconds_sum`, `extract_seconds_sum`, `record_seconds_sum` | Tổng giây của mọi record đã thử, gồm lỗi và record bị loại. Record time bao hàm load/extract, không cộng cả ba thành wall time. |
| `slot_acquire_count` | Số lần acquire global semaphore thực tế: serial theo batch, parallel theo worker; không gán một acquire cho mỗi record. |
| `slot_wait_seconds_sum`, `slot_wait_seconds_max` | Tổng và max thời gian acquire; không có semaphore thì số lần và thời gian đều bằng 0. |

Giữ các chỉ số legacy như `VERIFY_DETAIL_ATTEMPTED`, `VERIFY_DETAIL_FAILED`
theo phạm vi record public hiện tại. Dùng metrics toàn bộ ứng viên để phân tích
chi phí và tỷ lệ lỗi; không so hai bộ số có mẫu số khác nhau. Khi tổng hợp
nhiều job, các trường tổng được cộng, còn `scroll_rounds_max` và
`slot_wait_seconds_max` lấy max.

### Provenance của mỗi attempt

Manifest ghi `provenance.source.sha256` và danh sách file/hash đã sắp xếp,
`provenance.config.fingerprint_sha256` cùng CLI/config đã resolve, và metadata
Git gồm commit, dirty flag, hash diff source và các source chưa được track.
Source fingerprint chỉ theo runtime source; run/output identity, timestamp,
checklist, tài liệu, `.env`, venv và artifacts không thuộc comparison hash.
Destinations và stay dates đã parse vẫn thuộc cấu hình so sánh.

`provenance.versions` ghi Python, Playwright, OS và các phiên bản Chromium
quan sát từ browser đang dùng qua `chromium.observed_versions`; không mở thêm
browser chỉ để đo version. Xem status/count đi kèm khi không quan sát được
version; không coi giá trị thiếu là phiên bản đã xác minh. Metadata này tách
khỏi numeric metrics. Git không khả dụng được ghi rõ, không suy ra repo sạch.
Log provenance chỉ in bản tóm tắt an toàn; không in toàn bộ environment,
`.env`, raw diff, cookies hoặc thông tin đăng nhập.

## Thu CPU/RAM khi benchmark

Mỗi series dùng thư mục ignored `data/benchmarks/<series-id>/`. Giữ artifacts
cho từng run, kể cả run lỗi; không ghi hotel records hoặc diagnostics vào Git.

| Artifact | Nơi lưu |
| --- | --- |
| Lệnh, source/config fingerprints, UTC start/end | Snapshot cho từng run trong thư mục series; đối chiếu provenance của manifest. |
| stdout/stderr | `<run-id>.stdout.log`, `<run-id>.stderr.log` trong thư mục series. |
| CPU/RAM samples | `<run-id>.resources.jsonl` trong thư mục series. |
| JSONL public, manifest, diagnostics | Attempt output/debug gốc; ghi đường dẫn vào bảng kết quả, không sửa attempt cũ. |
| Kết quả aggregate | Bảng trong runbook với series/run identity, source/config, batch wall, public/discard, coverage và CPU/RAM. |

Sampler dưới đây chỉ theo dõi crawler PID và descendants, gồm Chromium xuất
hiện sau lúc bắt đầu. Không gộp các browser khác đang mở trên máy. Lệnh launch
benchmark cần giữ `$crawlerProcess` từ `Start-Process -PassThru -WindowStyle Hidden`
và redirect stdout/stderr; `$seriesDir` và `$runId` thuộc profile đã khóa.

Chạy đoạn attach này ngay sau launch. Không thực thi snippet bằng một crawler
mới chỉ để kiểm tra tài liệu:

```powershell
New-Item -ItemType Directory -Path $seriesDir -Force | Out-Null
$samplePath = [IO.Path]::GetFullPath((Join-Path $seriesDir "$runId.resources.jsonl"))
if (Test-Path -LiteralPath $samplePath) { throw "Resource sample file already exists" }
$sampler = Start-Job -ArgumentList $crawlerProcess.Id, $samplePath -ScriptBlock {
    param([int]$crawlerRootId, [string]$samplePath)
    $rootCreatedAt = $null
    while ($true) {
        $processRows = @(Get-CimInstance Win32_Process)
        $rootRow = $processRows | Where-Object ProcessId -EQ $crawlerRootId
        if (-not $rootRow) { break }
        if ($null -eq $rootCreatedAt) { $rootCreatedAt = $rootRow.CreationDate }
        if ($rootRow.CreationDate -ne $rootCreatedAt) { break }

        $treeIds = [Collections.Generic.HashSet[uint32]]::new()
        $null = $treeIds.Add([uint32]$crawlerRootId)
        do {
            $added = $false
            foreach ($processRow in $processRows) {
                if ($treeIds.Contains([uint32]$processRow.ParentProcessId)) {
                    if ($treeIds.Add([uint32]$processRow.ProcessId)) { $added = $true }
                }
            }
        } while ($added)

        $sampledAt = [DateTimeOffset]::UtcNow.ToString('o')
        $sampleLines = foreach ($processRow in $processRows) {
            if (-not $treeIds.Contains([uint32]$processRow.ProcessId)) { continue }
            $createdAt = $processRow.CreationDate.ToUniversalTime().ToString('o')
            [ordered]@{
                sampled_at_utc = $sampledAt
                process_key = "$($processRow.ProcessId):$createdAt"
                process_id = [int]$processRow.ProcessId
                parent_process_id = [int]$processRow.ParentProcessId
                name = $processRow.Name
                cpu_seconds = ([double]$processRow.KernelModeTime +
                    [double]$processRow.UserModeTime) / 10000000
                rss_bytes = [long]$processRow.WorkingSetSize
            } | ConvertTo-Json -Compress
        }
        [IO.File]::AppendAllLines($samplePath, [string[]]$sampleLines,
            [Text.UTF8Encoding]::new($false))
        Start-Sleep -Seconds 5
    }
}
try {
    $crawlerProcess.WaitForExit()
} finally {
    Wait-Job -Job $sampler -Timeout 10 | Out-Null
    if ($sampler.State -eq 'Running') { Stop-Job -Job $sampler }
    Receive-Job -Job $sampler
    Remove-Job -Job $sampler
}
```

Mỗi mốc lấy tổng `rss_bytes` của cây; peak RSS là giá trị lớn nhất trong các
mốc đã lấy, không phải RAM toàn máy. CPU-seconds sampled là tổng giá trị
`cpu_seconds` lớn nhất của từng `process_key`; không cộng CPU tích lũy qua các
mốc. PID kèm thời điểm tạo tránh gộp nhầm PID được tái sử dụng. Chu kỳ 5 giây có
thể bỏ lỡ tiến trình sống ngắn hoặc phần CPU sau sample cuối, nên báo đây là
samples và giữ cùng sampler cho mọi lượt. Thiếu samples hoặc sampler lỗi thì
ghi thiếu evidence, chưa quyết định cấu hình mặc định và không tự chạy thay mẫu.

## Test

```powershell
py -m pytest
```

## Optional local Databricks ETL tests

The Spark behavior tests are optional and do not add PySpark to the crawler's
runtime requirements. Install PySpark in the local test environment and use a
Java runtime supported by that PySpark version:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install pyspark==4.0.1
```

Bind Spark to the same local Python process for each test command. These
process-scoped settings avoid stale machine-level Spark paths:

```powershell
$env:SPARK_HOME = (Resolve-Path '.venv/Lib/site-packages/pyspark').Path
$env:PYSPARK_PYTHON = (Resolve-Path '.venv/Scripts/python.exe').Path
$env:PYSPARK_DRIVER_PYTHON = $env:PYSPARK_PYTHON
$env:JAVA_HOME = 'C:/Program Files/Java/jdk-21'
$env:SPARK_LOCAL_IP = '127.0.0.1'
& '.venv/Scripts/python.exe' -m pytest -m spark tests/test_databricks_spark.py
```

The shared Spark fixture uses `local[2]`, two shuffle partitions, and pytest
temporary directories for its warehouse and local scratch. If PySpark is not
installed, the Spark and ETL retry test modules are skipped. The retry tests
use stateful fakes and need the PySpark package for imports, but do not start
a JVM.
