# 🏋️ Prompt Caching Demo — FastAPI + LangGraph + OpenAI

Demonstrates **OpenAI prompt caching** in a LangGraph ReAct agent using FastAPI.
Two identical agents — one caches, one doesn't. One line of difference.

---

## The Result

| | No-Cache Agent | Cached Agent |
|---|---|---|
| Session timestamp position | **TOP** of system prompt | not in system prompt |
| cached_tokens per call | 0 | ~1920 (98%) |
| Cost per call | ~$0.000395 | ~$0.000270 |
| **Cost saving** | — | **~32% cheaper** |

---

## The One Difference

```python
# ❌ no_cache_agent.py — timestamp at TOP → new prefix every call → cache miss
timestamp     = datetime.now().isoformat()
system_prompt = f"[session: {timestamp}]\n\n{BASE_PROMPT}"

# ✅ cached_agent.py — BASE_PROMPT is the full system prompt → identical every call → cache hit
system_prompt = BASE_PROMPT
```

**Rule: static content first, dynamic content last (or in the user message).**

---

## Project Structure

```
prompt-caching-demo/
├── main.py                  ← FastAPI app: /chat/no-cache, /chat/with-cache, /warmup, /benchmark
├── agents/
│   ├── __init__.py
│   ├── shared_prompt.py     ← BASE_PROMPT (~1950 tokens) used by both agents
│   ├── no_cache_agent.py    ← ❌ timestamp at TOP → cache miss every call
│   └── cached_agent.py      ← ✅ static system prompt → cache hit every call
├── .env.example
├── requirements.txt
└── README.md
```

---

## Prerequisites

- Python 3.10+
- OpenAI API key → https://platform.openai.com/api-keys

---

## Setup

### 1. Clone and open in VS Code
```bash
git clone <your-repo>
cd prompt-caching-demo
```

### 2. Create virtual environment
```bash
python3 -m venv venv
```

**Activate — Mac/Linux:**
```bash
source venv/bin/activate
```

**Activate — Windows PowerShell:**
```bash
.\venv\Scripts\Activate.ps1
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
```bash
cp .env.example .env
```

Edit `.env`:
```env
OPENAI_API_KEY=sk-your-key-here
MODEL_NAME=gpt-4o-mini
```

### 5. Start the server
```bash
python -m uvicorn main:app --reload
```

> ⚠️ Always use `python -m uvicorn` (not just `uvicorn`) to ensure the venv Python is used.

Open Swagger UI: **http://localhost:8000/docs**

---

## Running the Demo

### Step 1 — Warm the cache
```
GET /warmup
```
Calls the cached agent 3 times. Watch the terminal — `cached_tokens` goes from 0 → 1920 after the first call. Cache is now hot.

### Step 2 — Compare individual calls
```
POST /chat/with-cache   {"message": "Should I do cardio before or after weights?"}
POST /chat/no-cache     {"message": "Should I do cardio before or after weights?"}
```
Watch `cached_tokens` in the response — 1920 vs 0.

### Step 3 — Run the benchmark
```
GET /benchmark
```
Runs no-cache agent 5x first, then cached agent 5x. Returns full cost and latency comparison.

Expected output:
```json
{
  "no_cache":   { "avg_cached_tokens": 0,    "avg_cost_per_call_usd": 0.000395 },
  "with_cache": { "avg_cached_tokens": 1920, "avg_cost_per_call_usd": 0.000270 },
  "improvement": {
    "cached_tokens_pct": 98.4,
    "cost_saving_pct": 31.8,
    "projected_monthly_saving_usd_at_10k_calls": 37.68
  }
}
```

---

## How OpenAI Prompt Caching Works

- Automatic — no API flag or configuration needed
- Activates when prompt prefix is **identical** and **>1024 tokens**
- Cached tokens billed at **50% of normal input price**
- Cache entries evict after ~5–10 minutes of inactivity
- In a multi-node LangGraph agent, every node that calls the LLM benefits → savings multiply

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: openai` | Use `python -m uvicorn` not `uvicorn` |
| `AuthenticationError` | Check `OPENAI_API_KEY` in `.env` — no extra spaces or quotes |
| `cached_tokens` always 0 | Run `/warmup` first; prompt must be >1024 tokens |
| Port already in use | `python -m uvicorn main:app --reload --port 8001` |
| `.env` not loading | Ensure `.env` is in same folder as `main.py` |
