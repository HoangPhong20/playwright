# Tài liệu dự án

`docs/` chứa tài liệu kỹ thuật dùng chung cho crawler, Airflow và Databricks.
Chọn tài liệu theo công việc thay vì đọc toàn bộ theo thứ tự.

## Đọc gì khi cần

| Nhu cầu | Tài liệu |
| --- | --- |
| Bắt đầu, cài môi trường và chạy pipeline đầy đủ | [README ở root](../README.md) |
| Hiểu luồng dữ liệu và tìm module cần sửa | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Chạy thử, benchmark và điều tra crawler local | [RUNBOOK.md](RUNBOOK.md) |
| Hiểu JSONL, dedupe, coverage và quality gates | [DATA_QUALITY.md](DATA_QUALITY.md) |
| Hiểu manifest, upload, batch identity và ingestion ledger | [DATABRICKS_INGESTION.md](DATABRICKS_INGESTION.md) |
| Vận hành Docker và Airflow DAG | [Airflow README](../airflow/README.md) |
| Upload source, setup bảng và cấu hình Databricks Job | [Databricks README](../databricks/README.md) |
| Sửa code theo quy ước repository | [AGENTS.md ở root](../AGENTS.md) |

## Quy ước tổ chức

- Giữ `README.md` ở root làm điểm vào của repository.
- Giữ một `AGENTS.md` ở root cho toàn repository, gồm cả quy tắc riêng của
  Airflow và Databricks trong các mục tương ứng.
- README của từng thành phần đặt cạnh source; `docs/` chỉ giữ kiến trúc,
  vận hành crawler và contract dùng chung. Không tạo bản sao của các README.
- Hướng dẫn sửa code nằm trong `AGENTS.md`; không duy trì thêm một change guide.
- Không dùng tài liệu làm bản chụp `.env` local. Giá trị fallback nằm trong
  [config.py](../agoda_crawler/config.py); `.env` là cấu hình runtime không commit.

Khi hành vi thay đổi, cập nhật tài liệu sở hữu nội dung đó và các liên kết
liên quan. Dùng code, contract YAML và test hiện tại để đối chiếu mô tả kỹ thuật.
