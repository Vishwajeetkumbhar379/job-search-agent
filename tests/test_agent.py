import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from job_search_agent.evaluate import Profile, evaluate, extract_requirements, is_target, lane
from job_search_agent.humanizer import lint, word_count_ok
from job_search_agent.llm import extract_with_claude
from job_search_agent.sources import parse_ashby, parse_greenhouse, parse_lever

FX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)
P = Profile.from_dict({
    "name": "Example Candidate", "years": 5, "seniority": 3,
    "skills": ["influencer marketing", "negotiation", "partnerships", "creator crms", "account management"],
    "domains": ["influencer", "creator", "partnerships", "brand"],
    "target_titles": ["partnerships", "influencer", "creator"],
    "languages": {"English": "Fluent", "German": "B1"},
    "base_city": "Berlin",
})


def gh():
    return parse_greenhouse("Acme", json.loads((FX / "greenhouse.json").read_text()))


def test_parsers_normalise_all_three_ats():
    assert len(gh()) == 2 and gh()[0].remote
    lv = parse_lever("Beta", json.loads((FX / "lever.json").read_text()))
    ab = parse_ashby("Gamma", json.loads((FX / "ashby.json").read_text()))
    assert lv[0].workplace == "hybrid" and "C1" in lv[0].description
    assert ab[0].compensation == "EUR 60K - 75K" and ab[0].remote


def test_requirements_come_from_the_ad():
    reqs, resps = extract_requirements(gh()[0])
    assert any("4+ years" in r.text and r.importance == "critical" for r in reqs)
    assert any("creator partnerships program" in r for r in resps)


def test_target_filter():
    jobs = gh()
    assert is_target(jobs[0], P, ["engineer"]) and not is_target(jobs[1], P, ["engineer"])


def test_good_fit_scores_high():
    e = evaluate(gh()[0], P, NOW)
    assert e.score >= 80 and e.lane.startswith("B")


def test_german_c1_is_a_blocker():
    lv = parse_lever("Beta", json.loads((FX / "lever.json").read_text()))[0]
    e = evaluate(lv, P, NOW)
    assert e.blockers and e.score <= 50


def test_work_from_anywhere_lane():
    ab = parse_ashby("Gamma", json.loads((FX / "ashby.json").read_text()))[0]
    assert lane(ab, P).startswith("A")


def test_missing_critical_caps_score():
    weak = Profile.from_dict({**P.__dict__, "years": 1, "skills": [], "languages": {}, "evidence": {}})
    assert evaluate(gh()[0], weak, NOW).score <= 79


def test_humanizer_catches_tells():
    text = "I am thrilled to apply. This is not just a job but a calling — truly! I leverage robust skills."
    kinds = {i.hint for i in lint(text)}
    assert any("Not-X-but-Y" in k for k in kinds)
    assert any("dash" in k for k in kinds)
    assert any(i.text.startswith("leverage") for i in lint(text))


def test_clean_text_passes():
    text = ("The Partnerships Manager role is close to work I did for five years. At Illuminati Media "
            "I led a team of twelve and managed creator deals for consumer brands. Your recent launch in "
            "France caught my attention because it needs local creators fast.")
    assert lint(text) == []


def test_word_count():
    ok, _ = word_count_ok("word " * 200, "email")
    assert ok


def test_claude_extraction_enforces_evidence_rules():
    job = gh()[0]
    block = SimpleNamespace(type="tool_use", input={"requirements": [
        {"text": "4+ years", "importance": "critical", "evidence": "stated", "quote": "4+ years in influencer marketing"},
        {"text": "Team player", "importance": "critical", "evidence": "inferred", "quote": ""},
        {"text": "Speaks Klingon", "importance": "high", "evidence": "stated", "quote": "Klingon required"},
    ]})
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(content=[block])))
    reqs = extract_with_claude(job, client=fake)
    assert reqs[0].importance == "critical"
    assert reqs[1].importance == "meaningful"
    assert reqs[2].evidence == "inferred" and reqs[2].importance == "meaningful"
