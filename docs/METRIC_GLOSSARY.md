# Metric glossary for the Decision/LLM prompt

- Mọi field kết thúc bằng `_vnd` là số nguyên VND, không phải triệu/tỷ rút gọn.
- `reserve_gap_vnd = cash_reserve_minimum_vnd - closing_cash_vnd`; tháng 2026-07 là 680,000,000.
- `funding_need_vnd = expected_cash_out_vnd + cash_reserve_minimum_vnd - expected_cash_in_vnd`; tháng 2026-07 là 1,190,000,000.
- `worst_month` phải được đọc cùng `worst_month_basis`; payload luôn phát cả funding need và reserve gap của tháng headline.
- `priority_rank` xếp invoice Open theo `invoice_amount_vnd` giảm dần; không dùng due date hoặc reliability.
- `high_risk_invoice_id` chọn reliability nhỏ nhất đã biết; customer thiếu mapping có reliability `null`, xếp cuối và sinh `ValidationIssue`.
