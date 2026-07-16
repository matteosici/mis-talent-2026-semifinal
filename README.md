# MIS Talent 2026 Semifinal — contract-first data layer

Repo này khóa contract giữa DS1 và lane Decision/LLM trước khi hoàn thiện business logic. Nguyên tắc tương thích đến ngày freeze: chỉ thêm field; không đổi tên hoặc xóa field. Mọi số tiền dùng hậu tố `_vnd`, mọi metric derived có `_basis`, và lựa chọn chưa chốt được đặt trong `config/policies.yaml`.

## Nguồn dữ liệu

Nguồn kiểm soát là `data/MISTalent2026_OPC_AgenticAI_TeamPack_v2-1.xlsx`. Loader dùng tên sheet thật trong workbook, không dùng số sheet đã stale trong `19_DATA_DICTIONARY`.

Audit hiện tại:

- Các primary key lõi của customers/contracts/products/orders/invoices không trùng.
- Join order→contract, order→service, invoice→order và invoice→customer không có orphan.
- Tổng invoice `Open` là 635,000,000 VND; priority là INV-004 → INV-002 → INV-003; high risk là INV-002.
- Cashflow có sáu tháng breach. Với policy mặc định `funding_need`, worst month là 2026-07 (1,190,000,000 VND). Nếu flip sang `reserve_gap`, worst month là 2026-06 (710,000,000 VND).

## Cấu trúc

- `src/contracts.py`: `FinanceOutput` và `RiskOutput` version 1.0.
- `src/resolvers.py`: các derivation thuần, policy-driven và fail-soft cho lookup.
- `src/validation.py`: cross-validation, data-health divergence và validator data dictionary.
- `fixtures/`: payload mẫu được tạo từ Team Pack thật.
- `docs/METRIC_GLOSSARY.md`: định nghĩa ngắn để đưa vào system prompt.
- `docs/SPEC_GAPS.md`: bằng chứng và resolution cho tám gaps.

## Chạy kiểm thử

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
```

Pytest đọc workbook thật và so sánh output với fixture, nên field rename, policy drift hoặc sai số sẽ fail ngay.

## Cam kết tích hợp với Ngọc

> Từ giờ tới freeze, DS1 chỉ thêm field, không đổi tên và không xóa field. Field nào có logic policy-driven đều có `_basis`; consumer đọc `_basis` thay vì đoán nghĩa từ số.
