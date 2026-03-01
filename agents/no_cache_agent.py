"""
NO-CACHE REACT AGENT
====================
LangGraph StateGraph with manual ReAct loop.
Simulates what many real apps do: session timestamp injected at the TOP of the
system prompt on every call — changing the prefix → cache miss every time.

Result: cached_tokens = 0 on every request — full cost every time.
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import TypedDict

from dotenv import load_dotenv
from openai import OpenAI
from langgraph.graph import StateGraph, END
from agents.shared_prompt import BASE_PROMPT

load_dotenv()

log    = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL  = os.getenv("MODEL_NAME", "gpt-4o-mini")

# ── Same static tool schema ───────────────────────────────────────────────────
TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_nutrition_info",
        "description": "Look up calories and protein per 100g for a food item.",
        "parameters": {
            "type": "object",
            "properties": {
                "food": {"type": "string", "description": "e.g. chicken breast, oats, eggs"}
            },
            "required": ["food"]
        }
    }
}]

FOOD_DATA = {
    "chicken breast": {"calories": 165, "protein_g": 31},
    "oats":           {"calories": 389, "protein_g": 17},
    "eggs":           {"calories": 155, "protein_g": 13},
    "rice":           {"calories": 130, "protein_g": 2.7},
    "salmon":         {"calories": 208, "protein_g": 20},
    "greek yogurt":   {"calories": 59,  "protein_g": 10},
    "banana":         {"calories": 89,  "protein_g": 1.1},
    "broccoli":       {"calories": 34,  "protein_g": 2.8},
}

def _call_tool(name: str, args: dict) -> str:
    if name == "get_nutrition_info":
        food = args.get("food", "")
        data = FOOD_DATA.get(food.lower().strip())
        if data:
            return f"{food}: {data['calories']} kcal, {data['protein_g']}g protein per 100g"
        return f"No data for '{food}'. Try: {', '.join(FOOD_DATA.keys())}"
    return "Unknown tool"


# ── State ─────────────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    system_prompt:     str           # dynamic — rebuilt each request
    messages:          list
    response:          str
    prompt_tokens:     int
    completion_tokens: int
    cached_tokens:     int


# ── ReAct node ────────────────────────────────────────────────────────────────
def react_node(state: AgentState) -> AgentState:
    """
    Full ReAct loop. Uses state["system_prompt"] which has timestamp at TOP.
    This breaks the cache prefix on every single request.
    """
    system_msg = {"role": "system", "content": state["system_prompt"]}
    messages   = list(state["messages"])

    total_prompt     = 0
    total_completion = 0
    total_cached     = 0
    final_response   = ""

    for iteration in range(5):
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[system_msg] + messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        usage        = completion.usage
        cached       = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        prompt_tok   = getattr(usage, "prompt_tokens", 0)
        complete_tok = getattr(usage, "completion_tokens", 0)

        total_prompt     += prompt_tok
        total_completion += complete_tok
        total_cached     += cached

        log.info("  │  iter=%d  prompt=%d  cached=%d  %s",
                 iteration + 1, prompt_tok, cached,
                 "❌ cache miss (expected)" if cached == 0 else f"⚠️ unexpected hit: {cached}")

        msg = completion.choices[0].message

        if msg.tool_calls:
            assistant_dict = {
                "role":       "assistant",
                "content":    msg.content or "",
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            }
            messages.append(assistant_dict)
            for tc in msg.tool_calls:
                args   = json.loads(tc.function.arguments)
                result = _call_tool(tc.function.name, args)
                log.info("  │  tool: %s(%s) → %s", tc.function.name, args, result)
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "content":      result,
                })
        else:
            final_response = msg.content or ""
            break

    return {
        **state,
        "messages":          messages,
        "response":          final_response,
        "prompt_tokens":     total_prompt,
        "completion_tokens": total_completion,
        "cached_tokens":     total_cached,
    }


# ── Graph ─────────────────────────────────────────────────────────────────────
def _build_graph():
    g = StateGraph(AgentState)
    g.add_node("react", react_node)
    g.set_entry_point("react")
    g.add_edge("react", END)
    return g.compile()

_graph = _build_graph()


# ── Public ────────────────────────────────────────────────────────────────────
def run_no_cache_agent(message: str) -> dict:
    log.info("━━━ [no-cache] NEW REQUEST ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ❌ Timestamp at TOP — exactly what real apps do with user IDs / session data
    # Changes the prefix on every call → cache miss guaranteed
    timestamp     = datetime.now().isoformat()
    system_prompt = f"[session: {timestamp}]\n\n{BASE_PROMPT}"
    log.info("  ❌ session timestamp at TOP — cache miss guaranteed: %s", timestamp)

    start  = time.perf_counter()
    result = _graph.invoke({
        "system_prompt":     system_prompt,
        "messages":          [{"role": "user", "content": message}],
        "response":          "",
        "prompt_tokens":     0,
        "completion_tokens": 0,
        "cached_tokens":     0,
    })
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    log.info("  latency=%dms  prompt=%d  cached=%d",
             latency_ms, result["prompt_tokens"], result["cached_tokens"])
    log.info("━━━ [no-cache] END ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    return {
        "response":          result["response"],
        "latency_ms":        latency_ms,
        "prompt_tokens":     result["prompt_tokens"],
        "completion_tokens": result["completion_tokens"],
        "cached_tokens":     result["cached_tokens"],
    }