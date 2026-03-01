import time
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from agents.no_cache_agent import run_no_cache_agent
from agents.cached_agent import run_cached_agent

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

app = FastAPI(
    title="Prompt Caching Demo",
    description="""Demonstrates OpenAI prompt caching vs no caching using a LangGraph ReAct agent.

**For a clean cache comparison use general fitness questions** (answered directly from the system prompt):
- "Should I do cardio before or after weights?"
- "How much protein do I need per day?"
- "What is progressive overload?"

**Tool-calling questions** (e.g. "how many calories in salmon?") trigger 2 LLM calls per request.
Call 2 always hits cache on both agents because the conversation history grows long enough
for OpenAI to find a matching prefix — this is correct OpenAI behaviour, not a bug.
The benchmark uses a direct-answer question to show the cleanest comparison.
""",
    version="1.0.0",
)

BENCHMARK_MESSAGE = "Should I do cardio before or after weights?"


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int


@app.post("/chat/no-cache", response_model=ChatResponse)
async def chat_no_cache(req: ChatRequest):
    log.info("→ /chat/no-cache  message=%r", req.message[:60])
    try:
        result = run_no_cache_agent(req.message)
        log.info(
            "← no-cache  latency=%.0fms  prompt=%d  cached=%d",
            result["latency_ms"], result["prompt_tokens"], result["cached_tokens"],
        )
        return result
    except Exception as e:
        log.error("no-cache error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/with-cache", response_model=ChatResponse)
async def chat_with_cache(req: ChatRequest):
    log.info("→ /chat/with-cache  message=%r", req.message[:60])
    try:
        result = run_cached_agent(req.message)
        log.info(
            "← with-cache  latency=%.0fms  prompt=%d  cached=%d",
            result["latency_ms"], result["prompt_tokens"], result["cached_tokens"],
        )
        return result
    except Exception as e:
        log.error("with-cache error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/warmup")
async def warmup():
    """
    Pre-warms the OpenAI cache by calling the cached agent 3 times.
    Run this BEFORE /benchmark or the live demo.
    Watch the logs — cached_tokens should go 0 → 1024+ after the first call.
    """
    WARMUP_MESSAGE = "What is a good pre-workout meal?"
    log.info("🔥 /warmup  pre-warming cache with 3 calls...")
    results = []
    for i in range(3):
        r = run_cached_agent(WARMUP_MESSAGE)
        results.append({"run": i + 1, "cached_tokens": r["cached_tokens"], "latency_ms": r["latency_ms"]})
        log.info("  warmup %d/3  cached=%d  latency=%.0fms", i + 1, r["cached_tokens"], r["latency_ms"])
    cache_hit = any(r["cached_tokens"] > 0 for r in results)
    log.info("🔥 warmup complete — cache %s", "✅ HOT" if cache_hit else "❌ still cold — run /warmup again")
    return {
        "status": "✅ cache hot" if cache_hit else "❌ still cold — run /warmup again",
        "runs":   results,
    }


@app.get("/benchmark")
async def benchmark():
    """
    Phase 1: all no-cache runs. Phase 2: all with-cache runs.
    Separated so OpenAI cache state is clean for each group.
    Run /warmup first to pre-warm the cache.
    """
    RUNS = 5
    log.info("▶ /benchmark  starting %d runs each...", RUNS)

    # Phase 1 — no-cache: all runs together, no cross-contamination
    log.info("  Phase 1: no-cache agent (%d runs)...", RUNS)
    no_cache_results = []
    for i in range(RUNS):
        log.info("  no-cache %d/%d", i + 1, RUNS)
        no_cache_results.append(run_no_cache_agent(BENCHMARK_MESSAGE))

    # Phase 2 — with-cache: all runs together, cache stays warm
    log.info("  Phase 2: with-cache agent (%d runs)...", RUNS)
    cached_results = []
    for i in range(RUNS):
        log.info("  with-cache %d/%d", i + 1, RUNS)
        cached_results.append(run_cached_agent(BENCHMARK_MESSAGE))

    def avg(results, key):
        return round(sum(r[key] for r in results) / len(results), 2)

    nc_latency    = avg(no_cache_results, "latency_ms")
    nc_prompt     = avg(no_cache_results, "prompt_tokens")
    nc_cached     = avg(no_cache_results, "cached_tokens")
    nc_completion = avg(no_cache_results, "completion_tokens")

    wc_latency    = avg(cached_results, "latency_ms")
    wc_prompt     = avg(cached_results, "prompt_tokens")
    wc_cached     = avg(cached_results, "cached_tokens")
    wc_completion = avg(cached_results, "completion_tokens")

    cached_tokens_pct   = round(wc_cached / wc_prompt * 100, 1) if wc_prompt else 0
    latency_improvement = round((nc_latency - wc_latency) / nc_latency * 100, 1) if nc_latency else 0

    # gpt-4o-mini pricing: $0.15/1M input, $0.075/1M cached input, $0.60/1M output
    INPUT_PRICE  = 0.15  / 1_000_000
    CACHED_PRICE = 0.075 / 1_000_000
    OUTPUT_PRICE = 0.60  / 1_000_000

    def calc_cost(prompt, cached, completion):
        return ((prompt - cached) * INPUT_PRICE) + (cached * CACHED_PRICE) + (completion * OUTPUT_PRICE)

    nc_cost = calc_cost(nc_prompt, nc_cached, nc_completion)
    wc_cost = calc_cost(wc_prompt, wc_cached, wc_completion)

    cost_saving_pct  = round((nc_cost - wc_cost) / nc_cost * 100, 1) if nc_cost else 0
    daily_saving_usd = round((nc_cost - wc_cost) * 10_000, 4)
    monthly_saving   = round(daily_saving_usd * 30, 2)

    summary = {
        "test_message": BENCHMARK_MESSAGE,
        "runs": RUNS,
        "no_cache": {
            "avg_latency_ms":        nc_latency,
            "avg_prompt_tokens":     nc_prompt,
            "avg_cached_tokens":     nc_cached,
            "avg_cost_per_call_usd": round(nc_cost, 6),
        },
        "with_cache": {
            "avg_latency_ms":        wc_latency,
            "avg_prompt_tokens":     wc_prompt,
            "avg_cached_tokens":     wc_cached,
            "avg_cost_per_call_usd": round(wc_cost, 6),
        },
        "improvement": {
            "latency_improvement_pct":                 latency_improvement,
            "cached_tokens_pct":                       cached_tokens_pct,
            "cost_saving_pct":                         cost_saving_pct,
            "projected_daily_saving_usd_at_10k_calls": daily_saving_usd,
            "projected_monthly_saving_usd_at_10k_calls": monthly_saving,
        },
    }

    log.info(
        "▶ benchmark complete  latency=%.1f%%  cached=%.1f%%  cost=%.1f%%  monthly=$%.2f",
        latency_improvement, cached_tokens_pct, cost_saving_pct, monthly_saving,
    )
    return summary


@app.get("/")
async def root():
    return {
        "message": "Prompt Caching Demo API",
        "endpoints": [
            "POST /chat/no-cache",
            "POST /chat/with-cache",
            "GET  /benchmark",
            "GET  /docs  ← Swagger UI",
        ],
    }