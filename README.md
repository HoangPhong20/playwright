# Agoda hotel data pipeline

Pipeline thu thập khách sạn Agoda bằng Playwright, điều phối bằng Airflow và
xử lý dữ liệu trên Databricks Unity Catalog.

```text
Airflow crawl
  -> verify JSONL + manifest
  -> upload UC Volume
  -> trigger Databricks Job
  -> Bronze -> Silver -> Gold
```

## Project flow

Xem [luồng hoạt động và công nghệ](docs/workflow.md) để đọc sơ đồ pipeline,
các bước crawler, Airflow, Bronze/Silver/Gold và cách xử lý retry. Airflow bàn
giao đúng batch bằng `manifest_path`; Gold tổng hợp toàn bộ lịch sử Silver.

## 1. Điều kiện cần

- Docker Desktop chạy Linux containers.
- Databricks workspace có Unity Catalog Volume:
  `/Volumes/agoda/raw/crawler`.
- Một Databricks Job gồm ba notebook tasks: Bronze, Silver và Gold.
- Token Databricks có API scopes `files` và `jobs`; token owner có quyền
  `Can Manage Run` trên Job.

## Windows development setup

Use the Windows Python launcher (`py`) for all local development commands.
It avoids relying on a `python` command being present on `PATH`; `python` inside
the Airflow Docker image is intentionally unchanged.

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -r requirements-dev.txt
py -m playwright install
py -B -m pytest -p no:cacheprovider
py -m ruff check .
py -m mypy agoda_crawler
```

If `py --list-paths` shows no installed Python, install a supported CPython
version first, then recreate `venv`. Do not reuse a virtual environment whose
base interpreter no longer exists.

## Databricks Free Edition và xác thực local

Free Edition không có Account Console hoặc API cấp account, nên không áp dụng
hướng dẫn tạo custom OAuth App tại `Settings > App connections` để lấy Client ID.
Xem [giới hạn Free Edition](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations#administrative-limitations).

Để kiểm tra truy cập workspace từ Windows bằng Databricks CLI, thay các giá trị
placeholder bằng workspace URL và tên profile bạn chọn:

```powershell
databricks auth login --host "https://<workspace-host>" --profile "<profile-name>"
databricks current-user me --profile "<profile-name>"
```

Luồng OAuth tích hợp của CLI không yêu cầu tự tạo custom OAuth Client ID.
Đăng nhập thành công chưa chứng minh có quyền đọc Volume hoặc chạy Job; cần
kiểm tra từng API cần dùng. Xem [OAuth cho CLI](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m).

Profile OAuth trên Windows không tự được chuyển vào Docker. Các script upload
và trigger của repository hiện khởi tạo SDK bằng `DATABRICKS_HOST` và
`DATABRICKS_TOKEN` từ môi trường container; chưa dùng profile OAuth local hoặc
tự refresh token. Không chép OAuth access token ngắn hạn vào `.env` như một giải
pháp chạy lịch lâu dài. Nếu API trả `Invalid access token`, cần xử lý thông tin
xác thực trước khi đánh giá quyền truy cập hoặc tính tương thích Free Edition.

## 2. Cấu hình root `.env`

Tạo hoặc cập nhật file `.env` tại root dự án. Không commit file này.

```dotenv
# Crawler
AGODA_DESTINATIONS=Vung Tau,Da Nang,Nha Trang,Ho Chi Minh
AGODA_MAX_PAGES=5
AGODA_HEADLESS=true

# Airflow
AIRFLOW_UID=50000
_AIRFLOW_WWW_USER_USERNAME=<airflow-user>
_AIRFLOW_WWW_USER_PASSWORD=<airflow-password>
AIRFLOW__CORE__FERNET_KEY=<fernet-key>
AIRFLOW__API_AUTH__JWT_SECRET=<jwt-secret>
AGODA_AIRFLOW_SCHEDULE="15 4 * * *"
AGODA_AIRFLOW_TIMEZONE=Asia/Ho_Chi_Minh
AGODA_CHECK_IN_OFFSET_DAYS=21
AGODA_AIRFLOW_OUTPUT_DIR=data/airflow
AGODA_LOCAL_RETENTION_DAYS=14

# Databricks
DATABRICKS_HOST=https://<workspace-host>
DATABRICKS_TOKEN=<token-with-files-and-jobs-scopes>
DATABRICKS_UC_VOLUME_PATH=/Volumes/agoda/raw/crawler
DATABRICKS_JOB_ID=<job-id>
DATABRICKS_JOB_TIMEOUT_SECONDS=3600
```

DAG chạy lúc **04:15** mỗi ngày theo `Asia/Ho_Chi_Minh`. Mỗi scheduled run
crawl một ngày check-in bằng cuối Airflow data interval cộng 21 ngày; check-out
tự động là ngày kế tiếp.

## 3. Setup Databricks một lần

### Upload source

Upload toàn bộ thư mục `databricks/` vào Workspace, ví dụ:

```text
/Workspace/Users/<your-email>/databricks
```

Không upload `__pycache__/` hoặc file `.pyc`.

### Tạo Unity Catalog tables

Chạy notebook sau một lần:

```text
/Workspace/Users/<your-email>/databricks/notebooks/setup_uc_objects_wrapper
```

Với parameter:

```text
project_root=/Workspace/Users/<your-email>/databricks
```

Kết quả mong đợi:

```text
{'status': 'success', 'tables_ready': 9}
```

For existing Unity Catalog tables, rerun `setup_uc_objects_wrapper` once after
uploading the new source and before the next daily Job. It adds
`raw_record_json` to Bronze and `quarantine_layer` to the quarantine table, and
performs the legacy `date`-to-`check_in_date` migration when needed. If an older
Silver table still has `record_hash`, drop that legacy column before the next
Job; the pipeline uses `record_id` as its idempotency key.

### Cấu hình Databricks Job

Tạo ba notebook tasks theo thứ tự:

```text
ingest_bronze_wrapper -> transform_silver_wrapper -> build_gold_wrapper
```

Mỗi task dùng Workspace notebook tương ứng trong `databricks/notebooks/`, và
có base parameters:

```text
project_root=/Workspace/Users/<your-email>/databricks
manifest_path={{job.parameters.manifest_path}}
```

Ở cấp **Job parameters**, tạo:

```text
manifest_path=__AIRFLOW_SUPPLIES_MANIFEST_PATH__
```

Airflow sẽ override `manifest_path` cho từng Job run. `agoda_etl/` là Python
package chứa logic; ba notebook chỉ nhận widgets rồi import và gọi package.

Chi tiết hơn xem [Databricks README](databricks/README.md).

## 4. Khởi động Airflow

Từ root dự án:

```powershell
docker compose -f airflow/docker-compose.yml build
docker compose -f airflow/docker-compose.yml up airflow-init
docker compose -f airflow/docker-compose.yml up -d
```

`airflow-init` có trạng thái `Exited (0)` là bình thường: đây là container khởi
tạo chạy một lần. Kiểm tra các service chính:

```powershell
docker compose -f airflow/docker-compose.yml ps
```

Mở <http://localhost:8080>, đăng nhập bằng `_AIRFLOW_WWW_USER_USERNAME` và
`_AIRFLOW_WWW_USER_PASSWORD` trong `.env`.

## 5. Chạy pipeline từ đầu đến cuối

1. Trong Airflow UI, mở DAG `agoda_daily_crawl` và bỏ pause.
2. Chọn **Trigger DAG** để tạo một DAG run mới.
3. Theo dõi các task:

   ```text
   crawl_agoda
     -> verify_output
     -> upload_to_uc_volume
     -> trigger_databricks_job
     -> cleanup_local_output
   ```

`trigger_databricks_job` lấy remote manifest path từ `upload_receipt.json` của
đúng crawler attempt, sau đó gọi Databricks Jobs API với:

```text
manifest_path=/Volumes/agoda/raw/crawler/.../run_manifest.json
```

Task chờ Job hoàn tất. Nếu Databricks Bronze, Silver hoặc Gold fail thì task
Airflow này fail và `cleanup_local_output` không chạy.

Để test với check-in date của Airflow interval hiện tại, nhập khi trigger:

```json
{"check_in_offset_days": 0}
```

Luôn tạo **DAG run mới** để chạy lại pipeline end-to-end. Clear/retry task
`trigger_databricks_job` của một run đã fail sẽ nhận lại Databricks run cũ do
idempotency token.

## 6. Kiểm tra kết quả

### Local Airflow output

```text
data/airflow/dag_id=<dag-id>/batch_id=<batch-id>/attempt=<n>/
  agoda_hotels_YYYY-MM-DD.jsonl
  run_manifest.json
  upload_receipt.json
```

JSONL chỉ chứa business fields của khách sạn. `run_manifest.json` là nguồn duy
nhất của `batch_id`, `airflow_run_id` và các metadata Airflow. `upload_receipt`
là biên lai local xác nhận các file đã được upload lên Volume.

### Unity Catalog Volume

```text
/Volumes/agoda/raw/crawler/
  dag_id=<dag-id>/
    batch_id=<batch-id>/
      attempt=<n>/
        agoda_hotels_YYYY-MM-DD.jsonl
        run_manifest.json
```

### Unity Catalog tables

Sau Job thành công, kiểm tra:

```text
agoda.raw.agoda_hotels_bronze
agoda.raw.agoda_ingestion_ledger
agoda.silver.agoda_hotels_history
agoda.gold.agoda_hotel_daily_summary
agoda.gold.agoda_destination_daily_summary
agoda.gold.agoda_rating_distribution
agoda.gold.agoda_price_by_star
```

Bronze và Silver idempotent theo `record_id`. Gold rebuild từ toàn bộ Silver
history để bảng tổng hợp luôn gồm cả dữ liệu cũ và batch mới.

Gold ghi bốn bảng tuần tự, không có transaction chung cho cả bốn bảng.
Chỉ sử dụng kết quả sau khi Job và audit Gold của lần refresh tương ứng đều
thành công; xem [hợp đồng publish Gold](databricks/README.md#gold-publication)
để xử lý refresh đang chạy hoặc thất bại.

## 7. Khi thay đổi code hoặc cấu hình

- Thay đổi crawler, Airflow scripts, `requirements.txt` hoặc Dockerfile:

  ```powershell
  docker compose -f airflow/docker-compose.yml build
  docker compose -f airflow/docker-compose.yml up -d --force-recreate
  ```

- Thay đổi `.env`: recreate Airflow services để nạp biến mới.
- Thay đổi `databricks/agoda_etl/` hoặc notebook: upload lại source lên cùng
  Workspace folder; sau đó chạy Job trực tiếp với một manifest có sẵn hoặc tạo
  DAG run Airflow mới.

## 8. Chạy crawler thủ công (tùy chọn)

Để debug ngoài Airflow, cần truyền run identity rõ ràng:

```powershell
$checkIn = (Get-Date).AddDays(21).ToString("yyyy-MM-dd")
$runId = "manual_$(Get-Date -Format 'yyyyMMdd_HHmmss_fffffff')"
py main.py --airflow-dag-id adhoc --airflow-run-id $runId `
  --airflow-try-number 1 --output-dir data/airflow `
  --destinations "Vung Tau" --date $checkIn --max-pages 1 `
  --workers 1 --no-enrich-details
```

Lệnh này chỉ crawl local; không tự upload hay trigger Databricks.

## Tài liệu chi tiết

- [Luồng hoạt động và công nghệ](docs/workflow.md)
- [Ngữ cảnh dự án](docs/PROJECT_CONTEXT.md)
- [Quy ước phát triển và skills](AGENTS.md)
- [Chạy crawler và benchmark](docs/RUNBOOK.md)
- [Data contract và quality rules](docs/DATA_QUALITY.md)
- [Airflow runbook](airflow/README.md)
- [Databricks ETL](databricks/README.md)
- [Manifest và ingestion contract](docs/DATABRICKS_INGESTION.md)
