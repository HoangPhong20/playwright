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

Truy cập <http://localhost:8080> và đăng nhập bằng `airflow` / `airflow`.
Đổi thông tin này trong `.env` nếu Airflow không chỉ chạy trên máy cá nhân.

Image custom có source crawler, Playwright và Chromium. Cấu hình crawler vẫn lấy
từ file `../.env`; file này không được copy vào image và không được commit.

## 2. Trigger DAG đầu tiên

Trong UI, vào **Admin → Variables** và tạo hai biến:

| Key | Ví dụ value |
| --- | --- |
| `agoda_check_in` | `2026-08-15` |
| `agoda_check_out` | `2026-08-16` |

Sau đó mở DAG `agoda_daily_crawl`, bỏ pause và chọn **Trigger DAG**.

DAG có hai task:

1. `crawl_agoda` chạy `main.py` với hai ngày từ Variables.
2. `verify_output` kiểm tra manifest hoàn tất, JSONL không rỗng và có ít nhất một record publishable.

Each Airflow run writes to an isolated `dag_id=<id>/batch_id=<id>/attempt=<n>`
directory below `data/airflow/`. Every JSONL record and manifest includes the
Airflow batch metadata. See `../docs/DATABRICKS_INGESTION.md` before adding a
Databricks loader.

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

## 4. Bước tiếp theo

Khi manual trigger ổn định, thay `schedule=None` trong DAG bằng lịch `08:00`
hằng ngày theo timezone `Asia/Ho_Chi_Minh`. Chỉ chuyển check-in sang ngày chạy
DAG hoặc “ngày chạy + N” sau khi đã chốt nhu cầu dữ liệu.
