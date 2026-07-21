# MIS Talent 2026 Semifinal — contract-first data layer

Repo này triển khai backend DS1 cho D1 bước 3 (Finance & Data Agent), D1 bước 4 (Risk & Compliance Agent) và structured handoff của Deliverable 5. Nguyên tắc tương thích đến ngày freeze: chỉ thêm field; không đổi tên hoặc xóa field. Mọi số tiền dùng hậu tố `_vnd`, mọi metric derived có `_basis`, và lựa chọn chưa chốt được đặt trong `config/policies.yaml`.

## Nguồn dữ liệu

Nguồn kiểm soát là `data/MISTalent2026_OPC_AgenticAI_TeamPack_v2-1.xlsx`. Loader dùng tên sheet thật trong workbook, không dùng số sheet đã stale trong `19_DATA_DICTIONARY`.

Golden behavior được đối chiếu với `../NhiemVuHeThong_Report.pdf`: D1 bước 3/4 ở trang 3, D5 mục 5.1/5.2 ở trang 8–10, và số liệu ReAct tại trang 19–21.

Audit hiện tại:

- Các primary key lõi của customers/contracts/products/orders/invoices không trùng.
- Join order→contract, order→service, invoice→order và invoice→customer không có orphan.
- Tổng invoice `Open` là 635,000,000 VND; priority là INV-004 → INV-002 → INV-003; high risk là INV-002.
- Cashflow có sáu tháng breach. Với policy mặc định `funding_need`, worst month là 2026-07 (1,190,000,000 VND). Nếu flip sang `reserve_gap`, worst month là 2026-06 (710,000,000 VND).
- Finance output có receivable aging, hai margin warnings, credit candidates `CR-004 → CR-001 → CR-002`, bridge 1.17B và decision package 1.37B.
- Risk output dùng threshold đọc từ `13_RISK_RULES`, tạo cluster TXN-006/007 exposure 178M, RR-005/RR-006 flags, execution risks và safe-handling notes đã mask/tokenize.

## Cấu trúc

- `src/contracts.py`: `FinanceOutput` và `RiskOutput` version 1.0.
- `src/resolvers.py`: các derivation thuần, policy-driven và fail-soft cho lookup.
- `src/rules.py`: parse threshold RR-001/RR-003/RR-005/RR-006/RR-007 từ `13_RISK_RULES`, fallback có issue rõ ràng.
- `src/risk.py`: transaction scan/cluster, governance, execution risk và masking D5.
- `src/security.py`: masking/tokenization theo `20_DATA_CLASS` và `21_MASKING_EXAMPLES`.
- `src/agents.py`: entrypoint chạy D1 bước 3/4 hoặc cả DS1 backend.
- `src/validation.py`: cross-validation, data-health divergence và validator data dictionary.
- `fixtures/`: payload mẫu được tạo từ Team Pack thật.
- `docs/METRIC_GLOSSARY.md`: định nghĩa ngắn để đưa vào system prompt.
- `docs/SPEC_GAPS.md`: bằng chứng và resolution cho tám gaps.
- `docs/DS1_SCOPE_MATRIX.md`: mapping code ↔ D1/D5 ↔ report.

## Chạy kiểm thử

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
```

Pytest đọc workbook thật và so sánh output với fixture, nên field rename, policy drift hoặc sai số sẽ fail ngay.

Chạy backend thật:

```python
from src import run_ds1_backend

output = run_ds1_backend()
print(output.finance.d5_handoff)
print(output.risk.d5_handoff)
```

Regenerate fixtures sau khi contract được duyệt:

```powershell
python scripts/generate_fixtures.py
```

Bank-product matching từ `11_BANK_PRODUCTS` được ingest và audit, nhưng không được chọn trong Finance/Risk Agent: report giao bước chọn package cuối cho Decision & Partner Agent.

## Ranh giới Decision & Partner prototype

- Bản local demo không yêu cầu đăng nhập. Repo không lưu username/password; nếu bản deploy có auth thì credentials phải được cấp qua secret manager ngoài repo.
- Decision Agent gọi OpenAI Responses API (`POST /v1/responses`) khi có `OPENAI_API_KEY`. Đây là API GA; khi thiếu key, payload không hợp lệ hoặc request lỗi, agent dùng deterministic fallback và ghi rõ `fallback`/`fallback_after_error`.
- Bank API là mock/sandbox, đọc endpoint và contract lỗi từ `12_API_CATALOG` + `22_SANDBOX_CONTRACT`; không có request nào được gửi tới ngân hàng thật. API-002 được tái sử dụng cho CR-001 vì catalog BTC không có endpoint vốn lưu động chuyên biệt, và mapping này được công khai trong code/output.
- `11_BANK_PRODUCTS` chỉ cung cấp `collateral_ratio`, không cung cấp `collateral_vnd` tuyệt đối. Các số collateral tuyệt đối trên Decision Card là **prototype fallback**, được gắn `collateral_basis=prototype_fallback_not_provided_by_11_BANK_PRODUCTS`, không phải dữ liệu ngân hàng xác nhận.
- Bảng tổng quan hợp đồng lấy metric từ `FinanceOutput.margin_analysis`; `customer_id`/`company_id` được token hóa ổn định trước khi render hoặc đưa vào evidence JSON.

## Cam kết tích hợp với Ngọc

> Từ giờ tới freeze, DS1 chỉ thêm field, không đổi tên và không xóa field. Field nào có logic policy-driven đều có `_basis`; consumer đọc `_basis` thay vì đoán nghĩa từ số.
