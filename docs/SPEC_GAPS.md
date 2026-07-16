# Resolution log for the eight specification gaps

Controlling source: `MISTalent2026_OPC_AgenticAI_TeamPack_v2-1.xlsx`. Contract shape is frozen at schema version 1.0; policy values may change behind resolvers.

| Gap | Evidence in Team Pack | Resolution | Regression test | Status |
| --- | --- | --- | --- | --- |
| 1. `service_id` absent from `04_CONTRACTS` | `06_ORDERS` contains `contract_id` and `service_id`; CON-004 maps to SVC-004 | Join through orders; no order returns `execution_feasible=null` plus `CONTRACT_ORDERS_NOT_FOUND`, never `False` | `test_feasibility_joins_via_orders`, `test_contract_without_orders_returns_none` | Closed |
| 2. Worst month Jun vs Jul | Reserve gap max: Jun 710M; funding need max: Jul 1,190M | Emit both metrics and read headline basis from YAML. Default `funding_need`; changing policy does not change fields | `test_worst_month_by_funding_need`, `test_worst_month_policy_flip` | Shape closed; policy confirmation pending |
| 3. `gap_magnitude` ambiguous | Jul reserve gap 680M differs from funding need 1,190M | Remove ambiguous name; use `_vnd` and explicit `_basis` | `test_both_gap_metrics_are_emitted`, fixture contract test | Closed |
| 4. `evidence_missing` absent | Only CR-003 note contains a blocking marker; AL-004 independently confirms missing document | Marker rule: missing/not provided/absent/thiếu/chưa có; the word `evidence` alone is not blocking | `test_evidence_missing_only_cr003`, `test_cr001_evidence_word_is_not_blocking` | Closed |
| 5. Invoice “rank” mixed two axes | Open amounts: INV-004 310M, INV-002 280M, INV-003 45M; reliabilities: 0.71, 0.64, 0.78 | Separate `priority_rank` (amount desc) and `high_risk_invoice_id` (minimum known reliability). Remove “due_date × reliability” | `test_priority_by_amount`, `test_high_risk_by_reliability` | Closed |
| 6. Unknown customer raises `KeyError` | Public perturbation may introduce CUS-099 | `.get()` lookup; reliability `null`, risk rank last, `CUSTOMER_NOT_FOUND` issue, pipeline continues | `test_unknown_customer_no_crash` | Closed |
| 7. Raw `approval_status` differs from DT-2 | CR-003: score 0.56, missing supplier confirmation, raw status `Review`; AL-004 confirms missing docs | Derive `Hold — No recommendation`, retain raw value and surface `DIV-001`; do not overwrite the mismatch | `test_dt2_diverges_from_raw_approval_status` | Closed as visible divergence |
| 8. `19_DATA_DICTIONARY` has stale sheet numbers | e.g. dictionary says `05_ORDERS`, actual workbook is `06_ORDERS`; `expected_reasoning` belongs to undistributed ground truth | Validate real `column_name` coverage, ignore dictionary sheet numbers, explicitly exclude round-controlled ground truth | `test_validator_ignores_dictionary_sheet_names` | Closed |

## Cross-validation result

Five independent checks match: CR-003 missing evidence, CON-002 margin pressure, 2026-07 reserve breach, TXN-006/007 anomaly cluster, and CON-004 contract/service value alignment. One mismatch is intentionally retained: DIV-001 for CR-003. Missing alerts are not treated as errors because `14_ALERTS` is not documented as exhaustive.

## Metric correction recorded during implementation

The earlier number list mixed grains. 635M is the total of three Open invoices, not a monthly cashflow metric. The six monthly `funding_need_vnd` values are 732M, 1,190M, 1,010M, -170M, 390M and 250M. This correction is locked by the finance fixture.
