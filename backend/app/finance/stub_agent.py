"""Scripted behaviour for LLM_PROVIDER=stub, so the application runs end to end with no model at all.

It walks the same tools a real model would for one fixed analysis (margin by region, latest two quarters).
It exists for key-less demos and load tests, and says so in its report.
"""

import json
import re

from app.llm.stub import reply
from app.llm.types import LLMResponse, Message, ToolCall, ToolSpec
from app.models.runs import HANDLE_PATTERN

SQL = """
SELECT region, to_char(date_trunc('quarter', order_date), 'YYYY-"Q"Q') AS quarter,
       sum(revenue_usd) AS revenue, sum(gross_profit_usd) AS gross_profit
FROM order_lines WHERE order_date >= '2026-04-01' GROUP BY 1, 2 ORDER BY 1, 2
""".strip()


def demo_responder(messages: list[Message], tools: list[ToolSpec]) -> LLMResponse:
    done = [c.name for m in messages if m.role == "assistant" for c in m.tool_calls]
    step = len(done)
    last_tool = next((m.content for m in reversed(messages) if m.role == "tool"), "")
    handle = (re.findall(HANDLE_PATTERN, " ".join(m.content for m in messages if m.role == "tool")) or [""])[0]

    def call(name: str, **arguments) -> LLMResponse:
        return reply(tool_calls=[ToolCall(f"stub_{step}", name, arguments)])

    question = next((m.content for m in messages if m.role == "user"), "").lower()
    if "alert" in question:  # the scripted path through an approval
        if step == 0:
            return call("propose_alert", metric="gross_margin", comparison="<", threshold=0.5, window="quarter",
                        rationale="Requested in the question (demonstration script).")  # fmt: skip
        outcome = "is now active" if "Approved" in last_tool else "was not created because an administrator rejected it"
        return call(
            "finish", summary=f"This is the built-in demonstration script, not a language model. The alert {outcome}."
        )
    if step == 0:
        return call("run_sql", sql=SQL, purpose="Revenue and gross profit by region for the latest two quarters")
    if step == 1:
        return call("compute", op="margin", args={"handle": handle, "revenue": "revenue", "profit": "gross_profit",
                                                  "group_by": ["region", "quarter"]})  # fmt: skip
    if step == 2:
        margin_handle = (re.findall(HANDLE_PATTERN, last_tool) or [handle])[0]
        return call("record_finding", claim="Gross margin by region and quarter was calculated from completed orders.",
                    evidence=[handle, margin_handle])  # fmt: skip
    if step == 3:
        return call(
            "finish",
            summary="This report was produced by the built-in demonstration script, not by a language model. "
            "It shows gross margin by region for the latest two quarters; open the evidence to see the figures.",
            findings=[1],
            recommendations=["Configure a model provider in Administration to ask your own questions."],
        )
    return reply(text=json.dumps({"note": "demo script complete"}))
