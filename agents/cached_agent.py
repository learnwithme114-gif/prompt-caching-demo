"""
CACHED AGENT
============
Uses the same BASE_PROMPT as the no-cache agent. The difference:
dynamic content (request_id) is appended at the BOTTOM — after the static block.

OpenAI caches from the START of the prompt. As long as the beginning is identical
across calls, the cache hits — even if something changes at the end.

Result: cached_tokens ≈ prompt_tokens on calls 2+ → faster + cheaper.
"""

import os
import uuid
import time
import logging
from typing import TypedDict

from openai import OpenAI
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv
from agents.shared_prompt import BASE_PROMPT   # ← same prompt as no-cache agent

load_dotenv()

log = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL  = os.getenv("MODEL_NAME", "gpt-4o-mini")


# ── LangGraph state ───────────────────────────────────────────────────────────
class AgentState(TypedDict):
    user_message: str
    response: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int


# ── Node ──────────────────────────────────────────────────────────────────────
def fitness_coach_node(state: AgentState) -> AgentState:
    # ✅  Dynamic content appended at the BOTTOM → static prefix unchanged → cache hit
    request_id    = str(uuid.uuid4())
    system_prompt = f"{BASE_PROMPT}\n\n[request_id: {request_id}]"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": state["user_message"]},
    ]

    completion = client.chat.completions.create(
        model=MODEL,
        messages=messages,
    )

    usage         = completion.usage
    cached_tokens = 0
    try:
        cached_tokens = usage.prompt_tokens_details.cached_tokens or 0
    except AttributeError:
        cached_tokens = 0

    return {
        **state,
        "response":          completion.choices[0].message.content,
        "prompt_tokens":     usage.input_tokens if hasattr(usage, "input_tokens") else usage.prompt_tokens,
        "completion_tokens": usage.output_tokens if hasattr(usage, "output_tokens") else usage.completion_tokens,
        "cached_tokens":     cached_tokens,
    }


# ── Build graph ───────────────────────────────────────────────────────────────
def _build_graph():
    g = StateGraph(AgentState)
    g.add_node("coach", fitness_coach_node)
    g.set_entry_point("coach")
    g.add_edge("coach", END)
    return g.compile()


_graph = _build_graph()


# ── Public interface ──────────────────────────────────────────────────────────
def run_cached_agent(message: str) -> dict:
    start = time.perf_counter()
    result = _graph.invoke({"user_message": message})
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    log.debug(
        "[with-cache] latency=%.0fms prompt=%d cached=%d",
        latency_ms, result["prompt_tokens"], result["cached_tokens"],
    )

    return {
        "response":          result["response"],
        "latency_ms":        latency_ms,
        "prompt_tokens":     result["prompt_tokens"],
        "completion_tokens": result["completion_tokens"],
        "cached_tokens":     result["cached_tokens"],
    }
