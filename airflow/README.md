# Airflow local cho Agoda crawler

Môi trường này dành cho học tập và chạy local. Nó dùng PostgreSQL +
`LocalExecutor`, nên không cần Redis hoặc Celery worker.

## 1. Khởi tạo

Từ thư mục này, build image và khởi tạo Airflow:

```powershell
docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml up airflow-init
docker compose -f docker-compose.yml up -d
```

After changing Airflow secrets or health-check configuration, recreate every
service so all containers use the same settings:

```powershell
docker compose -f docker-compose.yml up -d --force-recreate
```

Chỉ service `airflow-init` build image chung; các service Airflow khác dùng lại
đúng image đó. Điều này tránh Docker build cùng một tag song song.

Trước khi chạy, bảo đảm Docker Desktop đang mở và dùng Linux containers. Nếu
Docker báo không tìm thấy `dockerDesktopLinuxEngine`, hãy khởi động Docker
Desktop rồi đợi engine ở trạng thái **Running**.

Truy cập <http://localhost:8080> và đăng nhập bằng tài khoản cấu hình trong
root `../.env`:

```dotenv
_AIRFLOW_WWW_USER_USERNAME=<username>
_AIRFLOW_WWW_USER_PASSWORD=<password>
```

Image custom có source crawler, Playwright và Chromium. Cấu hình crawler vẫn lấy
từ file `../.env`; file này không được copy vào image và không được commit.

## 2. Lịch ngày crawl và manual trigger

DAG chạy lúc 08:00 mỗi ngày theo `Asia/Ho_Chi_Minh`. Mỗi scheduled run crawl
đúng một check-in date bằng ngày kết thúc data interval của Airflow cộng 21 ngày;
check-out là ngày kế tiếp. DAG không còn đọc Variables `agoda_check_in` hoặc
`agoda_check_out`.

Để trigger thủ công, mở DAG `agoda_daily_crawl`, bỏ pause và chọn **Trigger DAG**.
Khi cần đổi số ngày lead, nhập JSON sau trong trigger dialog:

```json
{"check_in_offset_days": 0}
```

Ví dụ trên crawl ngày của chính Airflow interval. Retry giữ nguyên interval và
check-in date, nên không làm ngày bị tăng thêm.

DAG có bốn task:

1. `crawl_agoda` chạy `main.py --date`; check-out được crawler tự tính là ngày kế tiếp.
2. `verify_output` kiểm tra manifest hoàn tất, JSONL không rỗng và có ít nhất một record publishable.
3. `upload_to_uc_volume` đưa JSONL và manifest lên `/Volumes/agoda/raw/crawler`; manifest được upload cuối cùng.
4. `cleanup_local_output` chỉ xóa output local đã upload thành công quá 14 ngày.

Each Airflow run writes to an isolated `dag_id=<id>/batch_id=<id>/attempt=<n>`
directory below `data/airflow/`. Every JSONL record and manifest includes the
Airflow batch metadata. Đặt `DATABRICKS_HOST`, `DATABRICKS_TOKEN` và
`DATABRICKS_UC_VOLUME_PATH` trong root `.env` trước khi chạy DAG; xem
`../docs/DATABRICKS_INGESTION.md` để biết layout và hợp đồng loader.

## Cấu hình DAG trong `.env`

Không cần sửa Python để đổi các giá trị vận hành sau:

```dotenv
AGODA_AIRFLOW_SCHEDULE="0 8 * * *"
AGODA_AIRFLOW_TIMEZONE=Asia/Ho_Chi_Minh
AGODA_CHECK_IN_OFFSET_DAYS=21
AGODA_AIRFLOW_OUTPUT_DIR=data/airflow
AGODA_LOCAL_RETENTION_DAYS=14
AGODA_AIRFLOW_RETRIES=1
AGODA_AIRFLOW_RETRY_DELAY_MINUTES=5
```

Sau khi đổi `.env`, recreate các Airflow services để container nhận biến mới.

Chỉ dùng một file cấu hình là root `../.env`. File này chứa cấu hình crawler,
Airflow và Databricks, gồm các biến Airflow sau:

```dotenv
AIRFLOW__CORE__FERNET_KEY=<fernet-key>
AIRFLOW__API_AUTH__JWT_SECRET=<jwt-secret>
_AIRFLOW_WWW_USER_USERNAME=<username>
_AIRFLOW_WWW_USER_PASSWORD=<password>
```

Không tạo lại `airflow/.env` và không commit root `.env`.

## 3. Lệnh vận hành

```powershell
# Xem tình trạng container
docker compose -f docker-compose.yml ps

# Xem scheduler log
docker compose -f docker-compose.yml logs -f airflow-scheduler

# Dừng nhưng giữ metadata PostgreSQL
docker compose -f docker-compose.yml down

# Xóa hoàn toàn metadata Airflow local (không xóa data/debug của crawler)
docker compose -f docker-compose.yml down --volumes --remove-orphans
```

Sau khi chỉnh `airflow/Dockerfile`, `requirements.txt` hoặc source crawler,
build lại image rồi khởi động lại services:

```powershell
docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml up -d
```

## 4. Vì sao không tăng ngày trong Variable

Check-in date được tính từ Airflow data interval, không từ một Variable có thể
bị thay đổi. Nhờ vậy retry, manual rerun hoặc task lỗi không thể bỏ qua ngày
hoặc tăng ngày hai lần.
