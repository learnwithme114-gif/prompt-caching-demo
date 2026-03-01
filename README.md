# 🏋️ Prompt Caching Demo — FastAPI + LangGraph + OpenAI

A minimal FastAPI app that demonstrates **OpenAI prompt caching** vs no caching
using LangGraph agents. Built for a YouTube tutorial showing real latency, token,
and cost differences side by side.

---

## What This Demo Shows

| | No-Cache Agent | Cached Agent |
|---|---|---|
| `request_id` position | **TOP** of system prompt | **BOTTOM** of system prompt |
| Cache hit after 1st call | ❌ Prefix changes every call | ✅ Prefix identical every call |
| `cached_tokens` | ~0 | ~83% of prompt tokens |
| Cost per call | Full price | ~49% cheaper |
| Latency | Baseline | ~10–15% faster |

**The entire lesson in one line:**

```python
# ❌ No-cache — UUID at TOP breaks the prefix → cache miss every call
system_prompt = f"[request_id: {request_id}]\n\n{BASE_PROMPT}"

# ✅ Cached — UUID at BOTTOM, static prefix intact → cache hit every call
system_prompt = f"{BASE_PROMPT}\n\n[request_id: {request_id}]"
```

---

## Project Structure

```
prompt-caching-demo/
├── main.py                      # FastAPI app + all endpoints
├── agents/
│   ├── __init__.py
│   ├── shared_prompt.py         # BASE_PROMPT used by both agents
│   ├── no_cache_agent.py        # ❌ UUID injected at TOP → cache miss
│   └── cached_agent.py          # ✅ UUID injected at BOTTOM → cache hit
├── .env.example
├── requirements.txt
└── README.md
```

---

## Prerequisites

- Python 3.10 or higher
- VS Code
- OpenAI API key → https://platform.openai.com/api-keys

---

## Setup in VS Code — Step by Step

### 1. Open the project in VS Code

```
File → Open Folder → select prompt-caching-demo
```

Open the integrated terminal: `Terminal → New Terminal` (or `` Ctrl+` ``)

---

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
```

**Activate (Mac/Linux):**
```bash
source venv/bin/activate
```

**Activate (Windows PowerShell):**
```bash
.\venv\Scripts\Activate.ps1
```

You should see `(venv)` at the start of your terminal prompt.

---

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

Verify openai installed correctly:
```bash
python -c "import openai; print(openai.__version__)"
```

---

### 4. Set up your .env file

```bash
cp .env.example .env
```

Open `.env` and fill in:
```env
OPENAI_API_KEY=sk-your-key-here
MODEL_NAME=gpt-4o-mini
```

---

### 5. Run the server

```bash
python -m uvicorn main:app --reload
```

> ⚠️ Always use `python -m uvicorn` (not just `uvicorn`) to ensure the venv Python is used.

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

---

---

## Reading the Terminal Logs

While the server runs, the terminal shows each call:

```
13:42:01 [INFO] → /chat/no-cache   latency=2398ms  prompt=1221  cached=0
13:42:03 [INFO] → /chat/with-cache latency=2060ms  prompt=1222  cached=1024
13:42:10 [INFO] ▶ benchmark complete  latency=14.0%  cached=83.8%  cost=49.0%  monthly=$72.00
```

---

## How Caching Works

```
No-cache agent — cache miss every call:
  Request → [request_id: abc123]\n\n{HUGE SYSTEM PROMPT} + user message
  Request → [request_id: xyz789]\n\n{HUGE SYSTEM PROMPT} + user message
             ↑ prefix changes → OpenAI can't cache → full cost every time

Cached agent — cache hit from call 2 onwards:
  Request → {HUGE SYSTEM PROMPT}\n\n[request_id: abc123] + user message
  Request → {HUGE SYSTEM PROMPT}\n\n[request_id: xyz789] + user message
             ↑ prefix identical → OpenAI caches it → 50% cheaper + faster
```

OpenAI caches automatically when:
1. Prompt is longer than **1024 tokens** ✓
2. The **prefix is byte-for-byte identical** across calls ✓
3. Same model ✓
4. Cache entry is recent (evicted after ~5 min of inactivity)

---


## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'openai'` | Use `python -m uvicorn` not `uvicorn` |
| `AuthenticationError` | Check `OPENAI_API_KEY` in `.env` |
| `cached_tokens` always 0 | Prompt may be under 1024 tokens — use `gpt-4o-mini` |
| Port already in use | `python -m uvicorn main:app --reload --port 8001` |
| `.env` not loading | Make sure `.env` is in the same folder as `main.py` |
| `invalid model ID` | Check exact model name — use `gpt-4o-mini` or `gpt-4.1-mini` |
