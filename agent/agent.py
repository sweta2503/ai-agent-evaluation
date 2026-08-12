"""
Customer Operations Agent — Groq-powered agentic loop.
"""
import json, os, time, random
from groq import Groq, RateLimitError, APIStatusError
from agent.tools import GROQ_TOOLS, TOOL_MAP

SYSTEM_PROMPT = """You are a Customer Operations Agent for an e-commerce company.

You have access to 7 tools. Use them to help resolve customer requests accurately and safely.

RULES:
1. Always resolve customer identity before taking any action (use search_customer first).
2. If multiple customers match, ask for clarification — never guess.
3. Before any refund or cancellation, call lookup_policy to verify eligibility.
4. Never take a destructive action (refund, address update) if the request is ambiguous.
5. If an order doesn't exist, say so — don't invent one.
6. Keep tool calls minimal — don't call tools you don't need.
7. After completing an action, confirm with send_customer_message.
"""

def run(task: str, max_turns: int = 10, verbose: bool = False) -> dict:
    """
    Run the agent on a single task.
    Returns: {response, tool_calls, turn_count, error}
    """
    client   = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": task},
    ]
    tool_calls_log = []
    turn = 0

    while turn < max_turns:
        turn += 1

        # call with exponential backoff on rate limits
        for attempt in range(6):
            try:
                resp = client.chat.completions.create(
                    model       = "llama-3.3-70b-versatile",
                    messages    = messages,
                    tools       = GROQ_TOOLS,
                    tool_choice = "auto",
                    max_tokens  = 4096,
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

        msg = resp.choices[0].message
        finish = resp.choices[0].finish_reason

        if verbose:
            print(f"\n── Turn {turn} | finish_reason: {finish}")

        messages.append(msg)

        if finish == "stop" or not msg.tool_calls:
            return {
                "response":   msg.content or "",
                "tool_calls": tool_calls_log,
                "turn_count": turn,
                "error":      None,
            }

        # Execute tool calls
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
