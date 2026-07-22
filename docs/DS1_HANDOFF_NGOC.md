# Bàn giao DS1 Backend cho Ngọc

Ngày cập nhật: 16/07/2026  
Project: `mis-talent-2026-semifinal`  
Phạm vi: Data Pipeline, Finance & Data Agent, Risk & Compliance Agent  
Nguồn kiểm soát: `../NhiemVuHeThong_Report.pdf` và `data/MISTalent2026_OPC_AgenticAI_TeamPack_v2-1.xlsx`

## 1. Kết luận bàn giao

Backend DS1 hiện đã chạy thật trên Team Pack Excel, không dùng payload giả và không nhúng các kết quả golden vào logic runtime. Hai entrypoint D1 bước 3 và bước 4 đã có thể chạy độc lập; `run_ds1_backend` chạy chung cả Finance và Risk trên cùng một lần load dữ liệu.

Kết quả QA tại thời điểm bàn giao:

- `30 passed` với workbook thật.
- Toàn bộ `src`, `tests` và `scripts` compile thành công.
- `pip check` trả về `No broken requirements found`.
- Audit xác nhận đủ 14/14 sheet DS1 bắt buộc: 8 sheet lõi và 6 sheet hỗ trợ join.
- Finance output khớp các số neo trong report.
- Risk output khớp RR-001, cluster, governance, execution risk và masking trong report.
- Perturbation tests chứng minh thay threshold trong `13_RISK_RULES` sẽ làm output thay đổi; kết quả không bị đóng cứng theo fixture.
- Payload Risk không chứa các raw restricted values đã kiểm tra: `CUS-005`, `OPC_MAIN`, `UNK-ECOM`, `eyJ...mock`.

## 2. Scope đã hoàn thành

### 2.1 Data ingestion và source audit

Loader dùng `pandas` để đọc workbook thật theo tên sheet. Không dựa vào số thứ tự sheet trong `19_DATA_DICTIONARY` vì các số này đã stale.

Tám sheet lõi DS1 được bắt buộc ingest/audit:

| Sheet | Số dòng hiện tại | Vai trò |
| --- | ---: | --- |
| `04_CONTRACTS` | 5 | Giá trị hợp đồng, margin, customer dependency |
| `09_CASHFLOW` | 6 | Breach, reserve gap, funding need theo tháng |
| `07_INVOICES` | 7 | Receivable aging và invoice priority |
| `08_BANK_TXN` | 10 | RR-001 transaction scan và clustering |
| `13_RISK_RULES` | 7 | Nguồn threshold/rule runtime |
| `14_ALERTS` | 5 | Reconcile kết quả derived với alert đã công bố |
| `10_CREDIT_PROFILE` | 4 | Credit ranking, RR-005 và RR-006 |
| `11_BANK_PRODUCTS` | 8 | Ingest/audit để downstream Decision Agent sử dụng |

Các sheet hỗ trợ cũng được audit vì cần cho join, target và safe handling:

- `02_OPC_PROFILE`
- `03_CUSTOMERS`
- `05_PRODUCTS`
- `06_ORDERS`
- `20_DATA_CLASS`
- `21_MASKING_EXAMPLES`

Các giá trị Excel date dạng serial được normalize thành ISO date, ví dụ `2026-...`, trước khi đi vào agent output.

### 2.2 D1 bước 3 — Finance & Data Agent

Finance Agent hiện thực hiện đầy đủ các nhóm logic sau.

#### Cashflow breach và funding gap

- `breach = projected_closing_cash < cash_reserve_minimum`.
- `reserve_gap_vnd = cash_reserve_minimum - projected_closing_cash`.
- `funding_need_vnd = expected_cash_out + cash_reserve_minimum - expected_cash_in`.
- Worst-month headline mặc định dùng `funding_need`, theo report.
- Severity theo funding gap:
  - `< 200M`: `Medium`.
  - `200M–500M`: `High`.
  - `> 500M`: `Critical`.
- Kết quả hiện tại: 6/6 tháng breach.
- Worst month: `2026-07`.
- Funding need tháng 07: `1,190,000,000 VND`.
- Severity theo sáu tháng: `Critical, Critical, Critical, High, High, High`.

Finance output vẫn phát cả `funding_need_vnd` và `reserve_gap_vnd`, kèm `_basis`, để downstream không phải suy đoán ý nghĩa metric.

#### Receivable aging

- Paid invoices: `45,000,000 VND`.
- Open invoices: `635,000,000 VND`.
- Not issued invoices: `2,760,000,000 VND`.
- Priority invoice theo amount: `INV-004 → INV-002 → INV-003`.
- High-risk invoice theo payment reliability: `INV-002`.
- Critical dependency: `INV-005 → CON-004`.
- Lookup customer dùng fail-soft: customer không tồn tại không làm pipeline crash; reliability trả `null` và sinh validation issue.

#### Margin analysis

- Threshold lấy từ `RR-003` trong `13_RISK_RULES`.
- Công thức gross profit: `contract_value_vnd * gross_margin`.
- Warning hiện tại: `CON-002`, `CON-004`.
- Gross profit của `CON-004`: `1,008,000,000 VND`.
- Nếu target trong `02_OPC_PROFILE` khác RR-003, hệ thống phát `MARGIN_THRESHOLD_DIVERGENCE`; RR-003 vẫn là rule điều khiển alert.

#### Credit candidates và funding plan

- Candidate ranking hiện tại: `CR-004 → CR-001 → CR-002`.
- `CR-002` là `borderline`, không bị loại chỉ vì score thấp hơn RR-006 khi chưa thiếu evidence.
- `CR-003` bị `hold` vì thiếu evidence.
- Priority bridge: `CR-004 + CR-001 = 1,170,000,000 VND`.
- Shortfall so với funding target: `20,000,000 VND`.
- Decision-package handoff: `CR-001 + CR-002 = 1,370,000,000 VND`.

Hai con số 1.17B và 1.37B là hai khái niệm khác nhau:

- `priority_bridge_amount_vnd`: tổ hợp candidate ưu tiên gần nhất nhưng không vượt funding target.
- `decision_package_total_ask_vnd`: main working-capital line cộng performance bond theo package mô tả trong report.

Finance Agent chỉ chuẩn bị structured handoff. Quyết định chọn sản phẩm ngân hàng cuối cùng không thuộc agent này.

### 2.3 D1 bước 4 — Risk & Compliance Agent

#### RR-001 transaction scan

- Threshold đọc từ `RR-001` trong `13_RISK_RULES`; hiện tại là `transaction_risk_score >= 85`.
- Findings hiện tại: `TXN-006`, `TXN-007`.
- Amount được phát dưới dạng absolute exposure cho risk summary.
- Account/counterparty trong finding chỉ phát token hoặc masked value, không phát raw identifier.

#### Transaction clustering

Hai giao dịch được nối thành cluster khi khớp ít nhất 2 trong 3 tiêu chí D5:

1. Cùng ngày.
2. Cùng counterparty.
3. Cùng normalized transaction pattern.

Kết quả hiện tại:

- Cluster: `TXN-006 + TXN-007`.
- Criteria match: `3/3`.
- Exposure: `178,000,000 VND`.
- Reconcile với `AL-001`: consistent.
- Severity: `Critical`.
- Hold payload: `temporary_hold`.
- Approver: `founder_confirmation_required`.
- `financial_flow_paused = true`.

Agent chỉ chuẩn bị hold payload và pause handoff; không tự gọi API hoặc thực thi đóng băng giao dịch.

#### Governance và credit risk

- RR-005 threshold: amount `> 300,000,000 VND` phải có human approval.
- Governance flags hiện tại: `CR-001`, `CR-002`, `CR-003`.
- RR-006 threshold: eligibility score `< 0.65`.
- `CR-002`: `borderline`.
- `CR-003`: `hold` vì đồng thời thiếu evidence.
- Governance flag là decision support, không phải approval.

#### Execution risk

- Orders flagged: `ORD-004`, `ORD-008`.
- Hai order cùng thuộc một contract nên được đánh dấu `systemic = true`.
- RR-007 late-delivery threshold: 7 ngày.
- Penalty rate lấy từ policy: `1.5%` order revenue/ngày.
- Potential penalty của `ORD-004`: `4,650,000 VND/ngày`.

#### Masking và tokenization

Safe handling dùng metadata từ `20_DATA_CLASS` và published examples từ `21_MASKING_EXAMPLES`.

| Raw value chỉ dùng nội bộ khi transform | Output an toàn |
| --- | --- |
| Customer identifier example | `TOK-CUS-A91F` |
| Account identifier example | `TOK-ACC-7D20` |
| Contract value `4,200,000,000` | `4.2B band` |
| Access token example | `[SECRET]` và `vault://sandbox/token` |

Metadata instruction cũng được sanitize để không echo một example identifier giống raw value vào payload.

## 3. Rule-driven design và nguyên tắc không hardcode

Runtime thresholds cho RR-001, RR-003, RR-005, RR-006 và RR-007 được parse từ `13_RISK_RULES` bằng operator/number trong `trigger_condition`.

Nếu một rule bị thiếu hoặc không parse được:

1. Hệ thống dùng giá trị fallback trong `config/policies.yaml`.
2. `ResolvedRule.source` được đặt thành `policy_fallback`.
3. Output sinh `ValidationIssue(code="RISK_RULE_FALLBACK")`.

Các số golden như `1.19B`, `178M`, `1.17B`, `1.37B` chỉ xuất hiện trong test assertion, fixture và tài liệu; logic runtime tính lại từ từng row của workbook.

Hai perturbation đã được khóa bằng test:

- Đổi RR-001 từ 85 lên 95 làm transaction findings và clusters trở thành rỗng, đồng thời `financial_flow_paused = false`.
- Đổi RR-003 từ 0.28 xuống 0.25 làm margin warning chỉ còn `CON-004`.

Lưu ý kỹ thuật: `reserve_breach_severity` vẫn còn trong `PolicyConfig`/YAML để giữ backward compatibility. Severity runtime hiện dùng hai threshold `high_gap_threshold_vnd` và `critical_gap_threshold_vnd`; không dùng field legacy này.

## 4. Tám specification gaps đã đóng

| Gap | Resolution đã triển khai | Trạng thái |
| --- | --- | --- |
| `service_id` không có trong contracts | Join `04_CONTRACTS → 06_ORDERS → 05_PRODUCTS`; thiếu order trả `null` và issue, không trả `False` giả | Closed |
| Worst month Jun hay Jul | Phát cả reserve gap và funding need; report xác nhận headline dùng funding need, tức Jul 1.19B | Closed |
| `gap_magnitude` mơ hồ | Dùng tên metric có `_vnd` và `_basis` rõ ràng | Closed |
| Không có field `evidence_missing` | Derive từ blocking markers; từ `evidence` đơn lẻ không bị xem là missing | Closed |
| Invoice “rank” trộn hai tiêu chí | Tách priority theo amount và high risk theo reliability | Closed |
| Unknown customer gây `KeyError` | Lookup fail-soft và phát `CUSTOMER_NOT_FOUND` | Closed |
| Raw approval status khác DT-2 | Giữ raw status, derive decision riêng và phát divergence thay vì overwrite | Closed |
| Data dictionary dùng số sheet stale | Validate theo column name và sheet name thật; loại ground-truth chưa phát hành | Closed |

Cross-validation hiện có 5 match và 1 divergence được cố ý giữ lại. `DIV-001` cho CR-003 là evidence của mismatch giữa raw `approval_status=Review` và derived `Hold — No recommendation`, không phải lỗi pipeline.

## 5. Public contracts và integration boundary

Các output chính:

- `FinanceOutput`
- `RiskOutput`
- `DS1BackendOutput`
- `FinanceHandoff`
- `RiskHandoff`
- `SourceAudit`
- `BusinessRuleSnapshot`

Nguyên tắc đến ngày freeze:

- Chỉ thêm field; không rename hoặc xóa field đang có.
- Mọi số tiền dùng hậu tố `_vnd`.
- Derived metric quan trọng phải có field/basis mô tả cách tính.
- Downstream đọc structured field, không parse message text.
- `schema_version` hiện là `1.0`.
- Fixtures là generated artifacts; không sửa tay.

Representative backend summary hiện tại:

```json
{
  "core_complete": true,
  "funding_need_vnd": 1190000000,
  "margin_warning_contract_ids": ["CON-002", "CON-004"],
  "credit_candidate_ids": ["CR-004", "CR-001", "CR-002"],
  "priority_bridge_amount_vnd": 1170000000,
  "decision_package_total_ask_vnd": 1370000000,
  "rr001_transaction_ids": ["TXN-006", "TXN-007"],
  "transaction_hold_amount_vnd": 178000000,
  "financial_flow_paused": true
}
```

Đây là summary để đọc nhanh, không thay thế schema đầy đủ trong `FinanceOutput`/`RiskOutput`.

## 6. File inventory của revision này

### File mới

- `src/agents.py`: entrypoint D1 bước 3, D1 bước 4 và full DS1 backend.
- `src/rules.py`: parse business rules từ sheet và explicit fallback.
- `src/risk.py`: transaction analysis, clustering, governance, execution risk và risk handoff.
- `src/security.py`: masking/tokenization helpers.
- `scripts/generate_fixtures.py`: regenerate output fixtures từ workbook thật.
- `docs/DS1_SCOPE_MATRIX.md`: mapping report → source sheet → code → golden output.
- `docs/DS1_HANDOFF_NGOC.md`: tài liệu bàn giao này.

### File đã cập nhật

- `src/contracts.py`: thêm các contract Finance/Risk/DS1 nhưng không xóa field cũ.
- `src/team_pack.py`: DS1 source list, date normalization và source audit.
- `src/resolvers.py`: Finance output, receivables, margin, credit candidates và handoff.
- `src/validation.py`: rule-driven data health và Risk output composition.
- `src/__init__.py`: export public entrypoints/output models.
- `config/policies.yaml`: explicit fallback thresholds và severity tiers.
- `tests/test_contracts.py`: golden, perturbation, masking và end-to-end tests.
- `fixtures/finance_output_sample.json`: generated Finance output.
- `fixtures/risk_output_sample.json`: generated Risk output.
- `docs/SPEC_GAPS.md`: eight-gap resolution log và DS1 revision note.
- `README.md`: cách chạy, architecture và scope boundary.

## 7. Cách Ngọc chạy lại

Chạy các command sau từ thư mục root `mis-talent-2026-semifinal`.

### Cài dependency nếu chưa có môi trường

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Chạy toàn bộ test

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected tại thời điểm bàn giao:

```text
..............................                                           [100%]
30 passed
```

### Chạy backend thật

```powershell
.\.venv\Scripts\python.exe -c "from src import run_ds1_backend; output = run_ds1_backend(); print(output.finance.d5_handoff); print(output.risk.d5_handoff)"
```

Hoặc dùng trong Python:

```python
from src import run_ds1_backend

output = run_ds1_backend()
finance_handoff = output.finance.d5_handoff
risk_handoff = output.risk.d5_handoff
```

Chạy riêng từng agent:

```python
from src import run_d1_step3_finance_agent, run_d1_step4_risk_agent

finance = run_d1_step3_finance_agent()
risk = run_d1_step4_risk_agent()
```

### Regenerate fixtures

Chỉ chạy sau khi thay đổi output contract/logic đã được review:

```powershell
.\.venv\Scripts\python.exe scripts\generate_fixtures.py
.\.venv\Scripts\python.exe -m pytest -q
```

Không regenerate fixture chỉ để làm test xanh. Khi fixture thay đổi, cần review diff và giải thích vì sao business output thay đổi.

## 8. Việc chuyển tiếp cho Ngọc

Ngọc tiếp quản từ trạng thái backend đã hoàn thành và nên thực hiện theo thứ tự sau.

### P0 — Trước khi tích hợp

1. Chạy `pytest` và xác nhận vẫn là 30/30.
2. Đọc `docs/DS1_SCOPE_MATRIX.md` để hiểu boundary theo report.
3. Inspect `FinanceHandoff` và `RiskHandoff`; downstream nên consume hai object này thay vì tự tính lại từ Excel.
4. Xác nhận code được commit trên một branch thống nhất trước khi merge, vì working tree hiện tại chưa được commit/push.

### P1 — Tích hợp vào orchestration/application

1. Gắn `run_d1_step3_finance_agent` vào D1 bước 3.
2. Gắn `run_d1_step4_risk_agent` vào D1 bước 4.
3. Nếu orchestration chạy hai agent song song, có thể dùng hai entrypoint độc lập; nếu muốn tránh đọc Excel hai lần, gọi `run_ds1_backend` và tách `finance`/`risk`.
4. Khi `risk.d5_handoff.financial_flow_paused` là `true`, không cho downstream phát lệnh tài chính tự động.
5. Hiển thị founder-approval requirement từ `transaction_hold`/`approval_requirement_record_ids`; không tự suy ra từ message.
6. Log source audit, applied rules và validation issues; không log raw restricted identifiers.

### P2 — Phần thuộc Decision & Partner Agent

`11_BANK_PRODUCTS` đã được load/audit nhưng Finance/Risk không chọn bank product. Theo report, Ngọc hoặc owner của Decision Agent cần:

1. Consume Finance/Risk handoff.
2. Match bank products từ `11_BANK_PRODUCTS`.
3. Chuẩn bị final decision package.
4. Tôn trọng `CR-003 hold`, RR-005 human approval và Risk pause.
5. Không biến recommendation thành autonomous approval/API execution.

### P3 — Connector/API execution nếu demo cần

Revision này không gọi external API và không thực thi hold. Nếu demo cần connector:

1. Nhận explicit founder confirmation.
2. Validate hold payload schema.
3. Chỉ gửi tokenized/masked identifiers qua trust boundary.
4. Ghi audit event, không ghi raw credential hoặc raw restricted identifier.
5. Giữ dry-run mặc định cho tới khi team duyệt quyền thực thi.

## 9. Acceptance checklist cho Ngọc

- [ ] `pytest` đạt 30/30 trên máy Ngọc.
- [ ] Workbook path resolve đúng từ project root.
- [ ] `source_audit.core_complete = true`.
- [ ] Finance worst month là `2026-07`, funding need `1.19B`.
- [ ] Margin warning chỉ gồm `CON-002`, `CON-004` với workbook hiện tại.
- [ ] Credit candidates là `CR-004`, `CR-001`, `CR-002`; `CR-003` hold.
- [ ] RR-001 findings là `TXN-006`, `TXN-007`.
- [ ] Cluster exposure là `178M`, alert `AL-001` consistent.
- [ ] `financial_flow_paused = true` trước founder confirmation.
- [ ] Payload/log không có raw `CUS-005`, `OPC_MAIN`, `UNK-ECOM`, access token.
- [ ] Decision Agent không tự tính lại Finance/Risk metrics.
- [ ] Không chọn bank product bên trong Finance/Risk Agent.
- [ ] Không execute transaction hold hoặc approval tự động.
- [ ] Mọi schema change sau bàn giao là additive-only hoặc có version/migration rõ ràng.
- [ ] Fixture chỉ regenerate sau khi review business-output diff.

## 10. Notes và caveats cần giữ nguyên

1. `11_BANK_PRODUCTS` là ingestion boundary của DS1 nhưng product-fit selection thuộc Decision & Partner Agent.
2. `14_ALERTS` không được mô tả là exhaustive. Thiếu alert tương ứng được ghi `not_checked`, không tự động kết luận contradiction.
3. `DIV-001` là divergence có chủ đích; không xóa chỉ để dashboard sạch.
4. Funding gap và reserve gap không đồng nghĩa. Headline report dùng funding need.
5. RR-001 cluster yêu cầu ít nhất 2/3 tiêu chí, không phải bắt buộc cả ba.
6. Critical transaction cluster chỉ tạo hold payload và pause flow; không gọi API.
7. `CR-002` là borderline, còn `CR-003` hold vì missing evidence.
8. RR-005 flag không đồng nghĩa record bị reject; nó yêu cầu human approval.
9. Threshold trong `13_RISK_RULES` là nguồn điều khiển runtime; YAML là explicit fallback.
10. Các sheet number trong `19_DATA_DICTIONARY` có thể stale; dùng real sheet names và column coverage.
11. Loader hiện là batch Excel ingestion. Chưa có watcher, database persistence hoặc incremental ingestion.
12. Repo hiện là Python backend/data package; chưa có REST API, UI hoặc production scheduler trong revision này.
13. Các thay đổi đang nằm trong working tree và chưa được commit/push tại thời điểm viết handoff.

## 11. Tài liệu nên đọc theo thứ tự

1. `docs/DS1_HANDOFF_NGOC.md` — bắt đầu từ đây.
2. `docs/DS1_SCOPE_MATRIX.md` — mapping scope/report/code.
3. `docs/SPEC_GAPS.md` — bằng chứng và resolution của 8 gaps.
4. `docs/METRIC_GLOSSARY.md` — định nghĩa metric cho prompt/downstream.
5. `src/contracts.py` — public contract cần giữ ổn định.
6. `src/agents.py` — integration entrypoints.
7. `tests/test_contracts.py` — executable acceptance criteria.

## 12. Điểm bàn giao cuối

Ngọc không cần viết lại logic Finance/Risk từ đầu. Phần cần làm tiếp là tích hợp các entrypoint và structured handoff vào orchestration/Decision Agent, giữ nguyên safety boundary, sau đó commit/merge theo workflow của team. Nếu một output thay đổi do workbook hoặc risk rule thay đổi, hãy kiểm tra `rule_snapshot`, `issues`, test perturbation và fixture diff trước khi kết luận đó là regression.
