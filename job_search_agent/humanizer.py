"""Lint application text for the patterns that make writing read as AI-generated.

Patterns adapted from github.com/blader/humanizer (MIT), which is based on
Wikipedia's "Signs of AI writing", then tuned on real application emails.
A recruiter skims dozens of these a day; these tells are what they notice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

STOCK_WORDS = [
    "crucial", "pivotal", "enhance", "showcase", "landscape", "vibrant", "meticulous", "intricate",
    "underscore", "garner", "bolster", "interplay", "delve", "leverage", "robust", "seamless",
    "cutting-edge", "spearhead", "testament", "tapestry", "navigate", "furthermore", "moreover",
]
CLICHES = [
    "passionate", "thrilled", "eager to", "great fit", "proven track record", "results-driven",
    "wealth of experience", "hit the ground running", "keen interest", "align perfectly", "resonates",
    "i am writing to", "i am confident that", "dear sir or madam", "to whom it may concern",
    "just checking in", "touching base", "circling back", "feel free to", "don't hesitate",
]
PATTERNS = [
    (r"\bnot (just|only|merely) [^.]{1,60}\bbut\b", "Not-X-but-Y contrast; state the point directly"),
    (r"\bit'?s not about\b", "Not-X-but-Y framing"),
    (r"\b(here'?s the thing|let'?s dive in|honestly\?)", "Staged run-up; start with the point"),
    (r"\b(at its core|the real question is|what really matters)\b", "Deep-sounding filler"),
    (r"\b(to be clear|don'?t get me wrong|i'?m not saying)\b", "Arguing with nobody"),
    (r", (highlighting|ensuring|showcasing|fostering|underscoring)\b", "Shallow -ing rider; keep the fact, drop the rider"),
    (r"\b(plays a (key|pivotal|crucial) role|serves as|stands as)\b", "Inflated phrasing; use is / has"),
    (r"[—–]", "Em or en dash; use a period, comma or colon"),
    (r"!", "Exclamation mark"),
    (r"[\U0001F300-\U0001FAFF☀-➿]", "Emoji"),
]


@dataclass
class Issue:
    line: int
    kind: str
    text: str
    hint: str

    def __str__(self) -> str:
        return f"line {self.line}: [{self.kind}] '{self.text}' · {self.hint}"


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]


def lint(text: str) -> list[Issue]:
    issues: list[Issue] = []
    for n, line in enumerate(text.splitlines(), 1):
        lo = line.lower()
        for w in STOCK_WORDS:
            for m in re.finditer(rf"\b{re.escape(w)}\w*", lo):
                issues.append(Issue(n, "stock word", line[m.start():m.end()], "Use a plainer word"))
        for c in CLICHES:
            if c in lo:
                issues.append(Issue(n, "cliche", c, "Cut or say something specific"))
        for pat, hint in PATTERNS:
            for m in re.finditer(pat, line, flags=re.I):
                issues.append(Issue(n, "pattern", m.group(0), hint))
    issues += rhythm(text)
    return issues


def rhythm(text: str) -> list[Issue]:
    out = []
    sents = _sentences(text)
    if len(sents) >= 4:
        starts_i = sum(1 for s in sents if re.match(r"^I\b", s))
        if starts_i / len(sents) > 0.5:
            out.append(Issue(0, "rhythm", f"{starts_i}/{len(sents)} sentences start with 'I'", "Vary sentence openers"))
        run = 0
        for s in sents:
            run = run + 1 if re.match(r"^I\b", s) else 0
            if run == 3:
                out.append(Issue(0, "rhythm", s[:40], "Three sentences in a row start with 'I'"))
        lengths = [len(s.split()) for s in sents]
        if max(lengths) - min(lengths) < 6:
            out.append(Issue(0, "rhythm", "uniform sentence length", "Mix short and long sentences"))
    for s in sents:
        if len(s.split()) <= 3 and s.endswith(".") and not re.match(r"^(Best|Thanks|Regards)", s):
            out.append(Issue(0, "rhythm", s, "Dramatic one-line closer; merge it into a sentence with a fact"))
    return out


def word_count_ok(text: str, kind: str) -> tuple[bool, str]:
    limits = {"email": (170, 270), "cover_letter": (300, 400), "follow_up": (60, 110), "connection_note": (0, 35)}
    lo, hi = limits[kind]
    n = len(text.split())
    return lo <= n <= hi, f"{n} words (target {lo}-{hi})"
