# Project context

Dự án thu thập quan sát khách sạn Agoda theo destination và ngày check-in,
phục vụ phân tích giá, rating, review và hạng sao.

```text
CLI / Airflow → Playwright crawler → JSONL + manifest
             → verify → Unity Catalog Volume → Databricks Bronze → Silver → Gold
```

Crawler chịu trách nhiệm tìm kiếm, thu listing, xác minh pagination và bổ sung
detail. Airflow bàn giao một attempt hoàn tất bằng `manifest_path`; Databricks
Job xử lý đúng batch đó và xây lại Gold từ toàn bộ lịch sử Silver.

Tài liệu theo trách nhiệm:

- [workflow.md](workflow.md): kiến trúc, công nghệ, luồng xử lý và bản đồ code.
- [AGENTS.md](../AGENTS.md): quy ước sửa code, skills và kiểm thử; đọc thêm
  `AGENTS.md` trong thư mục đang làm việc.
- [RUNBOOK.md](RUNBOOK.md): chạy crawler thủ công và benchmark concurrency.
- [DATA_QUALITY.md](DATA_QUALITY.md): output schema, dedupe và quality gates.
- [DATABRICKS_INGESTION.md](DATABRICKS_INGESTION.md): identity, manifest và hợp
  đồng bàn giao giữa Airflow và Databricks.

Giá trị fallback thuộc `agoda_crawler/config.py`; cấu hình thực thi lấy từ CLI,
environment và `.env`. Khi tài liệu lệch với triển khai, đối chiếu code và test
rồi cập nhật tài liệu liên quan.
