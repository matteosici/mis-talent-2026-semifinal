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

Expected: `30 passed`.

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

## 4. Live demo flow

1. Open Overview and show `DATA: LIVE EXCEL`, 8/8 DS1 core sheets loaded, input hash, timestamp.
2. Go to `CON-004 Detail`.
3. Show Finance Agent: 6/6 breach months, worst month 2026-07, credit ask 1.37B.
4. Show Risk Agent: TXN-006/TXN-007, 178M exposure, `BLOCKED BY CRITICAL RISK`.
5. Click `Approve AP-1 hold`.
6. Show Decision Agent bank fit matrix and Decision Card.
7. Highlight CR-003 missing supplier confirmation: agent asks for more information, does not invent evidence.
8. Use one final action button: Approve package / Reject / Request more info / Renegotiate.
9. Export or show runtime log preview under `System Evidence`.
