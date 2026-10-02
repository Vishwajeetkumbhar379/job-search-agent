"""Evaluate a job against a candidate profile, honestly.

Design rules (the same ones my live agent follows):
1. Read the job first, then the CV. Requirements are extracted from the job
   description alone, so the CV can't bias what counts as "required".
2. Every requirement carries evidence. A requirement guessed from context can
   never be marked critical.
3. Truth beats score. A missing critical requirement caps the score at 79,
   no matter how good everything else looks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .sources import Job

WEIGHTS = {"must_haves": 40, "responsibilities": 20, "seniority": 10, "domain": 10, "logistics": 20}

LANGUAGE_BLOCKERS = [
    r"\bC1\b", r"\bC2\b", r"verhandlungssicher", r"flie(ß|ss)end(es)? deutsch", r"native german",
    r"fluent (in )?german", r"german (is )?(required|a must)", r"muttersprach",
]
SENIORITY = {
    "junior": 1, "associate": 1, "intern": 0, "working student": 0, "werkstudent": 0,
    "specialist": 2, "manager": 3, "senior": 4, "lead": 4, "head": 5, "director": 6,
}
REQ_HEADERS = re.compile(r"^(requirements?|what you bring|who you are|you have|qualifications|must[- ]haves?|your profile|about you)\b", re.I)
PERKS = re.compile(r"\b(work from anywhere|remote[- ]first|fully remote|flexible hours|benefits?|vacation|equity)\b", re.I)
LANG_ALIASES = {"german": ("german", "deutsch"), "english": ("english", "englisch"), "french": ("french", "français")}
RESP_HEADERS = re.compile(r"^(what you('ll| will) do|responsibilities|the role|your role|about the role|in this role)\b", re.I)


@dataclass
class Profile:
    name: str
    years: int
    skills: list[str]
    domains: list[str]
    target_titles: list[str]
    languages: dict[str, str]
    seniority: int = 3
    home_country: str = "DE"
    base_city: str = "Berlin"
    evidence: dict[str, str] = field(default_factory=dict)  # skill -> one-line proof from the CV

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        low = lambda xs: [x.lower() for x in xs]
        return cls(d["name"], int(d["years"]), low(d["skills"]), low(d["domains"]), low(d["target_titles"]),
                   d.get("languages", {}), int(d.get("seniority", 3)), d.get("home_country", "DE"),
                   d.get("base_city", "Berlin"), {k.lower(): v for k, v in d.get("evidence", {}).items()})


@dataclass
class Requirement:
    text: str
    importance: str  # critical | high | meaningful | preferred
    evidence: str  # stated | inferred
    match: str = "MISSING"  # STRONG | PARTIAL | MISSING
    proof: str = ""


@dataclass
class Evaluation:
    job: Job
    score: int
    band: str
    lane: str
    requirements: list[Requirement]
    breakdown: dict[str, float]
    blockers: list[str]
    notes: list[str]


def _sections(text: str) -> tuple[list[str], list[str]]:
    reqs, resps, mode = [], [], None
    for raw in text.splitlines():
        line = raw.strip().lstrip("-•*").strip()
        if not line:
            continue
        if REQ_HEADERS.match(line):
            mode = "req"
            continue
        if RESP_HEADERS.match(line):
            mode = "resp"
            continue
        if raw.strip()[:1] in "-•*" or mode:
            (reqs if mode == "req" else resps if mode == "resp" else []).append(line)
    return reqs, resps


def extract_requirements(job: Job) -> tuple[list[Requirement], list[str]]:
    reqs, resps = _sections(job.description)
    out = []
    for r in reqs:
        lo = r.lower()
        if PERKS.search(lo):
            continue  # location and perks are logistics, not requirements
        if re.search(r"\b(must|required|\d+\+? years)\b", lo):
            imp = "critical"
        elif re.search(r"\b(nice to have|bonus|plus|ideally|preferred)\b", lo):
            imp = "preferred"
        else:
            imp = "high"
        out.append(Requirement(r, imp, "stated"))
    if not out:  # nothing stated: infer from the title, never as critical
        out.append(Requirement(f"Experience relevant to '{job.title}'", "meaningful", "inferred"))
    return out, resps


def _match(req: Requirement, p: Profile) -> None:
    lo = req.text.lower()
    yrs = re.search(r"(\d+)\+?\s*years", lo)
    if yrs:
        need = int(yrs.group(1))
        req.match = "STRONG" if p.years >= need else "PARTIAL" if p.years >= need - 1 else "MISSING"
        req.proof = f"{p.years} years of experience"
        if req.match != "MISSING":
            hit = [s for s in p.skills + p.domains if s in lo]
            if not hit and not any(d in lo for d in ("marketing", "partnership", "account")):
                req.match = "PARTIAL"
        return
    for lang, level in p.languages.items():
        if any(a in lo for a in LANG_ALIASES.get(lang.lower(), (lang.lower(),))):
            req.match = "STRONG" if level.upper() in ("NATIVE", "FLUENT", "C1", "C2") else "PARTIAL"
            req.proof = f"{lang}: {level}"
            return
    hits = [s for s in p.skills if s in lo]
    if hits:
        req.match = "STRONG"
        req.proof = p.evidence.get(hits[0], hits[0])
    elif any(w in lo for d in p.domains for w in d.split()):
        req.match = "PARTIAL"
        req.proof = "related domain experience"


def lane(job: Job, p: Profile) -> str:
    text = f"{job.location} {job.description}".lower()
    if re.search(r"work from anywhere|anywhere in the world|worldwide|fully distributed", text):
        return "A · anywhere"
    if job.remote or "remote" in job.location.lower():
        return "B · remote"
    if p.base_city.lower() in job.location.lower():
        return "C · " + p.base_city
    return "D · other"


def evaluate(job: Job, p: Profile, now: datetime | None = None) -> Evaluation:
    now = now or datetime.now(timezone.utc)
    reqs, resps = extract_requirements(job)
    for r in reqs:
        _match(r, p)

    def ratio(rs):
        if not rs:
            return 0.7
        pts = {"STRONG": 1.0, "PARTIAL": 0.5, "MISSING": 0.0}
        return sum(pts[r.match] for r in rs) / len(rs)

    must = [r for r in reqs if r.importance in ("critical", "high")]
    resp_text = " ".join(resps).lower()
    resp_hits = sum(1 for s in p.skills if s in resp_text)
    title = job.title.lower()
    job_level = max([v for k, v in SENIORITY.items() if k in title] or [3])
    blockers, notes = [], []

    text = job.description
    if any(re.search(pat, text, re.I) for pat in LANGUAGE_BLOCKERS):
        if p.languages.get("German", "").upper() not in ("C1", "C2", "NATIVE"):
            blockers.append("Requires business-level German")
    if job.posted and (now - job.posted).days > 30:
        notes.append(f"Posted {(now - job.posted).days} days ago; check it is still open")
    l = lane(job, p)

    breakdown = {
        "must_haves": WEIGHTS["must_haves"] * ratio(must),
        "responsibilities": WEIGHTS["responsibilities"] * min(1.0, 0.4 + 0.2 * resp_hits),
        "seniority": WEIGHTS["seniority"] * (1.0 if abs(job_level - p.seniority) <= 1 else 0.4),
        "domain": WEIGHTS["domain"] * (1.0 if any(d in (title + " " + text.lower()) for d in p.domains) else 0.3),
        "logistics": WEIGHTS["logistics"] * (0.0 if blockers else 1.0 if l[0] in "ABC" else 0.4),
    }
    score = round(sum(breakdown.values()))
    if any(r.importance == "critical" and r.evidence == "stated" and r.match == "MISSING" for r in reqs):
        score = min(score, 79)
        notes.append("A stated critical requirement is missing, so the score is capped at 79")
    if blockers:
        score = min(score, 50)
    band = "priority" if score >= 88 else "apply" if score >= 80 else "near miss" if score >= 72 else "skip"
    return Evaluation(job, score, band, l, reqs, {k: round(v, 1) for k, v in breakdown.items()}, blockers, notes)


def is_target(job: Job, p: Profile, exclude: list[str]) -> bool:
    t = job.title.lower()
    if any(x.lower() in t for x in exclude):
        return False
    return any(all(w in t for w in target.split()) for target in p.target_titles)
