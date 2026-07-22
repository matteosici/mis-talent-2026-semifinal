# MIS Talent Prototype Demo Quickstart

## 1. Setup once

Open PowerShell in this folder:

```powershell
cd "D:\MIS Talent Semi\mis-talent-2026-semifinal-feat-ds1-contract-freeze"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Optional OpenAI live mode:

```powershell
$env:OPENAI_API_KEY="paste_key_here"
$env:OPENAI_MODEL="gpt-4o"
```

Never paste the key into screenshots, README, terminal logs, or Git.

## 2. Confirm backend

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

Export real backend, Decision Card, and runtime log:

```powershell
.\.venv\Scripts\python.exe scripts\export_demo_outputs.py
```

Outputs:

- `output/demo_backend_output.json`
- `output/demo_decision_card.json`
- `runtime_logs/sample_runtime_log.json`

## 3. Run dashboard prototype

```powershell
.\.venv\Scripts\streamlit.exe run app.py --server.port 8501
```

Open: http://localhost:8501

The local demo intentionally has no login screen. No username/password is
stored in the repository. A hosted build must provision authentication through
the deployment platform if authentication is required.

OpenAI live mode uses the GA Responses API (`POST /v1/responses`), validates the
narrative schema before writing the Decision Card, and records `FAILED` or
`NOT_RUN` when it falls back after invalid output or a request error. Bank calls
are mock-only: the UI reads `12_API_CATALOG` and `22_SANDBOX_CONTRACT`, never sends a
real application, and can demonstrate safe failures after AP-4.

The Decision Agent prefers absolute `collateral_vnd` values from
`11_BANK_PRODUCTS`. Because the current Team Pack provides ratios but no
absolute values, the Decision Card uses and marks prototype fallbacks.

## 4. Live demo flow

1. Open Overview and show `DATA: LIVE EXCEL`, 14/14 DS1 sheets loaded (8 core + 6 supporting), input hash, timestamp.
2. Go to `CON-004 Detail`.
3. Show Finance Agent: 6/6 breach months, worst month 2026-07, credit ask 1.37B.
4. Show Risk Agent: TXN-006/TXN-007, 178M exposure, `BLOCKED BY CRITICAL RISK`.
5. Click `Approve AP-1 hold`.
6. Show Decision Agent bank fit matrix and Decision Card.
7. Highlight CR-003 missing supplier confirmation: agent asks for more information, does not invent evidence.
8. Use one final action button: Approve package / Reject / Request more info / Renegotiate.
9. Export or show runtime log preview under `System Evidence`.
