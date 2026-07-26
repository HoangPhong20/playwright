# Tài liệu dự án

Thư mục này chứa ngữ cảnh vận hành và kỹ thuật cho người phát triển và model làm việc với crawler.
`README.md` và `AGENTS.md` ở root vẫn là điểm vào và quy ước bắt buộc của repository.

Đọc theo thứ tự:

1. [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md): mục tiêu, luồng chạy và ranh giới module.
2. [RUNBOOK.md](RUNBOOK.md): setup, lệnh chạy và benchmark runtime.
3. [DATA_QUALITY.md](DATA_QUALITY.md): schema output, dedupe và tiêu chí chất lượng.
4. [DATABRICKS_INGESTION.md](DATABRICKS_INGESTION.md): manifest và layout Unity Catalog Volume.
5. [CHANGE_GUIDE.md](CHANGE_GUIDE.md): cách sửa code an toàn và test cần chạy.

Khi tài liệu mâu thuẫn với code, code và test hiện tại là nguồn sự thật. Cập nhật tài liệu cùng thay đổi code.
