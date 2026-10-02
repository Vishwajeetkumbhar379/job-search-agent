"""Optional Claude pass: extract a requirement table from a job description as structured JSON.

The rule-based extractor works offline. This layer is better at messy, prose-style
job ads, and still follows the same evidence rules.
"""
from __future__ import annotations

import os

from .evaluate import Requirement
from .sources import Job

MODEL = os.environ.get("JOB_AGENT_MODEL", "claude-sonnet-4-5")

TOOL = {
    "name": "record_requirements",
    "description": "Record every requirement in the job description.",
    "input_schema": {
        "type": "object",
        "properties": {
            "requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "importance": {"enum": ["critical", "high", "meaningful", "preferred"]},
                        "evidence": {"enum": ["stated", "inferred"]},
                        "quote": {"type": "string", "description": "Verbatim words from the ad, empty if inferred"},
                    },
                    "required": ["text", "importance", "evidence", "quote"],
                },
            }
        },
        "required": ["requirements"],
    },
}

SYSTEM = (
    "You extract job requirements for a careful recruiter. Read only the job description. "
    "A requirement is 'stated' only if you can quote it word for word. Inferred requirements "
    "can never be critical or high. Do not look at any candidate information."
)


def extract_with_claude(job: Job, client=None) -> list[Requirement]:
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_requirements"},
        messages=[{"role": "user", "content": f"Job title: {job.title}\nCompany: {job.company}\n\n{job.description}"}],
    )
    block = next(b for b in msg.content if getattr(b, "type", "") == "tool_use")
    reqs = []
    for r in block.input["requirements"]:
        imp, ev = r["importance"], r["evidence"]
        if ev == "inferred" and imp in ("critical", "high"):
            imp = "meaningful"  # enforce the evidence rule even if the model slips
        if ev == "stated" and r.get("quote", "").strip().lower() not in job.description.lower():
            ev = "inferred"  # a "quote" that isn't in the ad is not evidence
            imp = "meaningful" if imp in ("critical", "high") else imp
        reqs.append(Requirement(r["text"], imp, ev))
    return reqs
