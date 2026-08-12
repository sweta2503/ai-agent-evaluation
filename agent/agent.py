"""
Customer Operations Agent — Claude-powered agentic loop.
"""
import json, os
import anthropic
from agent.tools import TOOLS, TOOL_MAP

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
    client   = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    messages = [{"role": "user", "content": task}]
    tool_calls_log = []   # [{tool, input, output, turn}]
    turn = 0

    while turn < max_turns:
        turn += 1
        resp = client.messages.create(
            model    = "claude-sonnet-4-6",
            max_tokens = 4096,
            system   = SYSTEM_PROMPT,
            tools    = TOOLS,
            messages = messages,
        )

        if verbose:
            print(f"\n── Turn {turn} | stop_reason: {resp.stop_reason}")

        # Collect assistant message
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "end_turn":
            final_text = next(
                (b.text for b in resp.content if hasattr(b, "text")), ""
            )
            return {
                "response":    final_text,
                "tool_calls":  tool_calls_log,
                "turn_count":  turn,
                "error":       None,
            }

        if resp.stop_reason != "tool_use":
            return {
                "response":   "",
                "tool_calls": tool_calls_log,
                "turn_count": turn,
                "error":      f"Unexpected stop_reason: {resp.stop_reason}",
            }

        # Execute all tool calls in this turn
        tool_results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input
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
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": block.id,
                "content":     result,
            })

        messages.append({"role": "user", "content": tool_results})

    return {
        "response":   "Max turns reached without a final answer.",
        "tool_calls": tool_calls_log,
        "turn_count": turn,
        "error":      "max_turns_exceeded",
    }
