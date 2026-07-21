# DS1 implementation matrix

Controlling narrative: `../NhiemVuHeThong_Report.pdf`. The implementation follows D1 steps 3/4 and the structured outputs in Deliverable 5; appendices 4.3 and 5.1 provide the golden values.

| Report scope | Source sheets | Implementation | Observable output | Golden evidence |
| --- | --- | --- | --- | --- |
| Finance T0a: customer intake gate | `04_CONTRACTS`, `03_CUSTOMERS` | `customer_intake`, `build_finance_output` | Per-opportunity verified status and real reliability; unknown/blank customer produces a structured issue; aggregate `customer_verified` handoff flag | Agent Logic Spec DT-0A |
| Finance T0b: operational feasibility gate | `04_CONTRACTS`, `06_ORDERS`, `05_PRODUCTS` | `resolve_execution_feasibility`, `build_finance_output` | Per-opportunity `true`/`false`/`null` result plus issues; aggregate `execution_feasible` handoff flag | Agent Logic Spec DT-0B; Report service/value join |
| D1 step 3 / D5 Finance T1: cashflow monitoring | `09_CASHFLOW`, `13_RISK_RULES` | `build_cashflow_report`, `run_d1_step3_finance_agent` | 6/6 breaches; Jul funding need 1.19B; severity Critical/Critical/Critical/High/High/High | Report pp. 3, 9, 19–20 |
| D5 Finance T2: receivable aging | `07_INVOICES`, `03_CUSTOMERS`, `06_ORDERS` | `build_receivable_aging` | Open 635M; Not issued 2.76B; high risk INV-002; dependency INV-005→CON-004 | Report pp. 9, 20 |
| D5 Finance T3: margin + credit candidates | `04_CONTRACTS`, `02_OPC_PROFILE`, `10_CREDIT_PROFILE`, `13_RISK_RULES` | `build_margin_analysis`, `build_credit_candidates`, `build_credit_plan` | Warnings CON-002/CON-004; CR-004→CR-001→CR-002; bridge 1.17B; decision package 1.37B; CR-003 hold | Report pp. 9, 19–21 |
| D1 step 4 / D5 Risk T1: transaction anomaly | `08_BANK_TXN`, `13_RISK_RULES`, `14_ALERTS` | `analyze_transaction_risk`, `run_d1_step4_risk_agent` | RR-001 threshold 85; TXN-006/007; 3/3 cluster; exposure 178M; hold payload prepared; finance flow paused | Report pp. 3, 9–10, 19–20 |
| D5 Risk T2: governance | `10_CREDIT_PROFILE`, `13_RISK_RULES` | `build_governance_flags` | RR-005: CR-001/002/003; RR-006: CR-002 borderline, CR-003 hold | Report pp. 9–10, 20–21 |
| D5 Risk T2: execution risk | `06_ORDERS`, `02_OPC_PROFILE`, `13_RISK_RULES` | `build_execution_risks` | ORD-004/008 systemic; ORD-004 potential penalty 4.65M/day after threshold 7 days | Report pp. 9, 20–21 |
| D5 safe handling | `20_DATA_CLASS`, `21_MASKING_EXAMPLES` | `safe_handle_value`, `build_report_safe_handling_notes` | CUS-005→TOK-CUS-A91F; OPC_MAIN→TOK-ACC-7D20; 4.2B band; access token→vault | Report pp. 3, 9, 21 |
| D5 structured handoff | All outputs above | `FinanceHandoff`, `RiskHandoff`, `run_ds1_backend` | Stable payload for the Decision & Partner Agent; no API execution or autonomous approval | Report pp. 8–10 |

## Source boundary

The ingestion audit requires the eight DS1 core sheets named in the assignment and the supporting sheets needed by D1/D5 joins. `11_BANK_PRODUCTS` is loaded and audited, but product-fit selection is intentionally outside Finance/Risk: section 5.3 assigns bank matching and final package selection to the Decision & Partner Agent.

## Safety boundary

The Risk Agent prepares a transaction-hold payload but never executes API-006. `financial_flow_paused=true` remains active while the Critical cluster lacks founder confirmation. Governance flags are decision support, not approvals.

Finance Task 0a/0b follows the same producer boundary: the agent emits structured gate evidence, aggregate handoff flags and validation issues, but never early-exits or changes an application/contract state. Pause/skip and `NOT_RECOMMEND` behavior belongs to the later orchestration task.

## Method lock-ins

- Finance T2 keeps `high_risk_invoice_id=INV-002` using minimum known payment reliability. This deliberately replaces the earlier ambiguous Report wording “due_date × reliability”; collection `priority_rank` remains a separate amount-descending axis.
- Risk RR-007 remains unchanged: `execution_risks` contains ORD-004 and ORD-008, both systemic for CON-003, with potential penalties of 4.65M VND/day and 6.3M VND/day respectively.
