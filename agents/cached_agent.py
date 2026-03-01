"""
CACHED REACT AGENT
==================
LangGraph StateGraph with manual ReAct loop.
System prompt is 100% STATIC — BASE_PROMPT only, never changes.
Identical bytes sent to OpenAI on every single call → cache hit from call 2.

The user message and conversation history come AFTER the static prefix
so they never affect caching.

Result: cached_tokens ≈ 90%+ of prompt tokens → up to 50% cost saving.
"""

import os
import json
import time
import logging
from typing import TypedDict, Annotated
import operator

from dotenv import load_dotenv
from openai import OpenAI
from langgraph.graph import StateGraph, END
from agents.shared_prompt import BASE_PROMPT

load_dotenv()

log    = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL  = os.getenv("MODEL_NAME", "gpt-4o-mini")

# ── Static tool schema — same bytes every call ────────────────────────────────
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
    messages:          list          # plain list — no reducer, we manage it ourselves
    response:          str
    prompt_tokens:     int
    completion_tokens: int
    cached_tokens:     int


# ── ReAct node ────────────────────────────────────────────────────────────────
def react_node(state: AgentState) -> AgentState:
    """
    Full ReAct loop inside a single node.
    Reason → Act (tool call if needed) → Observe → Reason again → Answer.
    System prompt is BASE_PROMPT — static, never mutated.
    """
    # ✅ BASE_PROMPT is the ONLY system prompt — 100% static every call
    system_msg = {"role": "system", "content": BASE_PROMPT}
    messages   = list(state["messages"])  # copy — don't mutate state

    total_prompt     = 0
    total_completion = 0
    total_cached     = 0
    final_response   = ""
    max_iterations   = 5

    for iteration in range(max_iterations):
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[system_msg] + messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        usage         = completion.usage
        cached        = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        prompt_tok    = getattr(usage, "prompt_tokens", 0)
        complete_tok  = getattr(usage, "completion_tokens", 0)

        total_prompt     += prompt_tok
        total_completion += complete_tok
        total_cached     += cached

        log.info("  │  iter=%d  prompt=%d  cached=%d  completion=%d  %s",
                 iteration + 1, prompt_tok, cached, complete_tok,
                 "✅ CACHE HIT" if cached > 0 else "❌ cold start")

        msg = completion.choices[0].message

        if msg.tool_calls:
            # Act: execute tools, append results, loop back to Reason
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
            # Final answer
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
def run_cached_agent(message: str) -> dict:
    log.info("━━━ [with-cache] NEW REQUEST ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("  ✅ system prompt = BASE_PROMPT only — 100%% static every call")

    start  = time.perf_counter()
    result = _graph.invoke({
        "messages":          [{"role": "user", "content": message}],
        "response":          "",
        "prompt_tokens":     0,
        "completion_tokens": 0,
        "cached_tokens":     0,
    })
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    log.info("  latency=%dms  prompt=%d  cached=%d  %s",
             latency_ms, result["prompt_tokens"], result["cached_tokens"],
             "✅ CACHE HIT" if result["cached_tokens"] > 0 else "❌ cold start")
    log.info("━━━ [with-cache] END ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    return {
        "response":          result["response"],
        "latency_ms":        latency_ms,
        "prompt_tokens":     result["prompt_tokens"],
        "completion_tokens": result["completion_tokens"],
        "cached_tokens":     result["cached_tokens"],
    }