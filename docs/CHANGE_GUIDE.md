# Hướng dẫn thay đổi cho model và developer

## Trước khi sửa

1. Đọc `AGENTS.md`, rồi đọc `docs/PROJECT_CONTEXT.md` và module cần sửa.
2. Xác định thay đổi thuộc navigation, listing, extraction, enrichment, orchestration hay utility; giữ `main.py` chỉ làm parse/handoff.
3. Kiểm tra worktree để không ghi đè thay đổi không liên quan.

## Quy tắc thiết kế

- Ưu tiên helper/module hiện có thay vì thêm logic chéo giữa nhiều layer.
- Giữ type hints cho public function và PEP 8.
- Selector thay đổi ở `extraction/selectors.py`; parser thuần ở `extraction/parsers.py`; không nhét parser vào navigation/crawler.
- Pagination phải có evidence xác minh trạng thái mới trước khi merge record.
- Dedupe dùng helper trong `listing/records.py`, không tự tạo key khác ở caller.
- Detail concurrency chỉ dùng tên `detail_concurrency`.
- Không log credential, cookie, PII hay output crawl lớn.

## Khi thay đổi cấu hình hoặc CLI

Phải cập nhật đồng thời:

1. `main.py` cho CLI.
2. `config.py` cho `.env` override nếu hỗ trợ biến môi trường.
3. Default trong `orchestration.py` hoặc module sở hữu hành vi.
4. Test parser/config trong `tests/test_main.py`.
5. Tài liệu liên quan trong `docs/`.

Không tạo alias cấu hình trùng nghĩa trừ khi có kế hoạch deprecate rõ ràng.

## Xác minh tối thiểu

```powershell
python -m pytest
python main.py --destinations "Vung Tau" `
  --date-start 2026-08-15 --date-end 2026-08-15 `
  --max-pages 1 --workers 1 --no-enrich-details `
  --output-dir data/raw/smoke_after_change
```

Khi thay đổi live crawler, kiểm tra ít nhất: `pages`, `duplicate`, số record, coverage field bắt buộc và timing. Không dùng full crawl làm test đầu tiên.
