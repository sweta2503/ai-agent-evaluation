"""
Customer Operations Agent — Groq-powered agentic loop.
Supports two reproducible agent versions:
  v1 — basic system prompt, minimal guidance
  v2 — improved prompt with explicit reasoning steps and guardrails
"""
import json, os, time, random
from groq import Groq, RateLimitError, APIStatusError
from agent.tools import GROQ_TOOLS, TOOL_MAP

# ── V1: Basic prompt — minimal guidance ───────────────────────
V1_SYSTEM_PROMPT = """You are a Customer Operations Agent for an e-commerce company.
You have access to tools to look up orders, issue refunds, update addresses, and contact customers.
Help the customer with their request."""

# ── V2: Improved prompt — explicit rules and guardrails ───────
V2_SYSTEM_PROMPT = """You are a Customer Operations Agent for an e-commerce company.

You have access to 7 tools. Use them to help resolve customer requests accurately and safely.

RULES — follow these in order:
1. IDENTIFY before acting. Use search_customer first. If multiple customers match a name, ask for clarification — never guess.
2. VERIFY the order. Call get_order to confirm the order exists and belongs to the right customer.
3. CHECK POLICY before any refund or cancellation. Call lookup_policy first, every time.
4. DO NOT ACT on ambiguous requests. If the request is unclear about which customer, order, or action, ask.
5. NEVER invent orders or customer IDs. If get_order returns not-found, say so.
6. USE MINIMUM TOOLS. Don't call tools you don't need for this specific request.
7. CONFIRM actions. After a refund or address update, send the customer a confirmation via send_customer_message.

For policy-restricted actions (refund outside 30 days, address update on shipped order):
— Explain the policy clearly. Do not execute the action."""


def run(task: str, version: str = "v1", max_turns: int = 10,
        verbose: bool = False) -> dict:
    """
    Run the agent on a single task.
    Returns: {response, tool_calls, turn_count, error}
    """
    system_prompt = V2_SYSTEM_PROMPT if version == "v2" else V1_SYSTEM_PROMPT

    client   = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": task},
    ]
    tool_calls_log = []
    turn = 0

    while turn < max_turns:
        turn += 1

        for attempt in range(6):
            try:
                resp = client.chat.completions.create(
                    model       = "llama-3.3-70b-versatile",
                    messages    = messages,
                    tools       = GROQ_TOOLS,
                    tool_choice = "auto",
                    max_tokens  = 4096,
                    temperature = 0,   # deterministic — only variable is the agent version
                )
                break
            except RateLimitError:
                wait = (2 ** attempt) + random.uniform(0, 1)
                print(f"   [rate limit] waiting {wait:.1f}s (attempt {attempt+1}/6)...")
                time.sleep(wait)
            except APIStatusError as e:
                if e.status_code in (500, 502, 503):
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    print(f"   [server error {e.status_code}] retrying in {wait:.1f}s...")
                    time.sleep(wait)
                else:
                    raise
        else:
            return {
                "response":   "Rate limit retries exhausted.",
                "tool_calls": tool_calls_log,
                "turn_count": turn,
                "error":      "rate_limit_exhausted",
            }

        msg    = resp.choices[0].message
        finish = resp.choices[0].finish_reason

        if verbose:
            print(f"\n── Turn {turn} | finish: {finish}")

        messages.append(msg)

        if finish == "stop" or not msg.tool_calls:
            return {
                "response":   msg.content or "",
                "tool_calls": tool_calls_log,
                "turn_count": turn,
                "error":      None,
            }

        for tc in msg.tool_calls:
            tool_name  = tc.function.name
            tool_input = json.loads(tc.function.arguments)

            if verbose:
                print(f"   → {tool_name}({json.dumps(tool_input)[:120]})")

            try:
                fn     = TOOL_MAP[tool_name]
                result = fn(**tool_input)
            except Exception as e:
                result = json.dumps({"error": str(e)})

            if verbose:
                print(f"   ← {result[:120]}")

            tool_calls_log.append({
                "turn":   turn,
                "tool":   tool_name,
                "input":  tool_input,
                "output": result,
            })
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      result,
            })

    return {
        "response":   "Max turns reached without a final answer.",
        "tool_calls": tool_calls_log,
        "turn_count": turn,
        "error":      "max_turns_exceeded",
    }
