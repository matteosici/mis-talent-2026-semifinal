# Design QA — Dashboard financial-result formatting

## Comparison Target

- Source visual truth: screenshots attached to the user request on 2026-07-23; the chat surface did not expose a local source-image path.
- Supporting baseline captures: `tmp/qa-streamlit-final3/implementation-decision-ready.png` and `tmp/qa-streamlit-final3/implementation-final-active.png`.
- Implementation: `app.py`, served locally on port 8501.
- Intended desktop viewport: 1440 px wide, matching the supplied screenshots.
- State: CON-004 contract detail after AP-1 approval.

## Requested Visual Changes

- “Kết quả phân tích sức khỏe tài chính tổng thể của OPC” and “Dòng tiền & Gói tín dụng” use the same large heading rank.
- The cash-flow section order is heading, chart/tabs, then the two yellow insight cards.
- “Decision & Partner Agent · Bằng chứng bổ sung” uses the same neutral white/gray card treatment as the Finance and Risk agent frames.
- “Bằng chứng kỹ thuật · Decision & Partner” renders after the two-column dashboard content as the last expander.

## Verification Evidence

- Streamlit UI state and ordering assertions: `tests/test_streamlit_ui.py`.
- `.\.venv\Scripts\python.exe -m pytest tests/test_streamlit_ui.py -q`: 9 passed.
- `.\.venv\Scripts\python.exe -m pytest -q`: 87 passed.
- Python compilation: passed.
- The local Streamlit server started successfully on port 8501.

## Fidelity Surfaces

- Fonts and typography: the overview title is now 22 px/1.25/850 weight, matching the existing large section-title scale; it drops to 20 px and stacks cleanly on mobile.
- Spacing and layout rhythm: the overview heading has expanded padding and bottom spacing; the cash-flow heading precedes the tabs/chart and yellow cards; the technical expander is outside and below both dashboard columns.
- Colors and visual tokens: the supplemental-evidence card now uses `var(--line)`, white background, neutral status badge, and the same subtle elevation as the agent containers.
- Image quality and assets: no image assets were added or replaced.
- Copy and content: all dashboard copy and live values are unchanged.

## Findings

- [P2] Current browser-rendered comparison is unavailable.
  - Evidence: the in-app browser reported `Browser is not available: iab`; the default browser reported `No browser is available`.
  - Impact: the current implementation could not be captured at the reference viewport, compared side by side with the supplied screenshots, or checked for browser console errors.
  - Fix: reopen this project with an available browser surface and capture the AP-1-approved state at 1440 px.

## Comparison History

- Previous baseline QA passed against the earlier dashboard composition in `tmp/qa-streamlit-final3/`.
- Current iteration updated structure, heading scale, card tokens, responsive behavior, and UI-order assertions.
- Post-fix browser evidence is blocked because no supported browser surface is available in this session.

## Implementation Checklist

- [x] Reorder heading, chart, and yellow cards.
- [x] Promote the OPC analysis title to the large heading scale.
- [x] Neutralize the supplemental-evidence card treatment.
- [x] Move Decision & Partner technical evidence to the bottom.
- [x] Pass the complete automated test suite.
- [ ] Capture and visually compare the current browser-rendered AP-1-approved state.

final result: blocked
