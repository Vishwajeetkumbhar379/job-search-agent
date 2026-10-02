"""Job sources: the public job-board APIs behind most startup careers pages.

Reading the ATS API instead of scraping HTML or job aggregators means every
listing is live, complete and current. Aggregators often lag by weeks.
"""
from __future__ import annotations

import html
import json
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

UA = {"User-Agent": "job-search-agent/0.1 (+https://github.com/Vishwajeetkumbhar379/job-search-agent)"}


@dataclass
class Job:
    source: str
    company: str
    title: str
    location: str
    url: str
    posted: datetime | None
    description: str
    remote: bool = False
    workplace: str = ""
    compensation: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.company.lower()}::{self.title.lower()}"


def _strip_html(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<\s*(li)[^>]*>", "\n- ", s, flags=re.I)
    s = re.sub(r"<\s*(br|/p|/h\d|/li|/ul)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def _dt(v) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, tz=timezone.utc)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def parse_greenhouse(company: str, data: dict) -> list[Job]:
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append(Job("greenhouse", company, j["title"], loc, j["absolute_url"], _dt(j.get("updated_at")),
                       _strip_html(j.get("content", "")), remote="remote" in loc.lower()))
    return out


def parse_lever(company: str, data: list) -> list[Job]:
    out = []
    for j in data:
        cats = j.get("categories") or {}
        lists = "\n".join(f"{l.get('text', '')}\n{_strip_html(l.get('content', ''))}" for l in j.get("lists", []))
        wt = (j.get("workplaceType") or "").lower()
        out.append(Job("lever", company, j["text"], cats.get("location", ""), j["hostedUrl"], _dt(j.get("createdAt")),
                       (j.get("descriptionPlain") or "") + "\n" + lists, remote=wt == "remote", workplace=wt))
    return out


def parse_ashby(company: str, data: dict) -> list[Job]:
    out = []
    for j in data.get("jobs", []):
        comp = (j.get("compensation") or {}).get("compensationTierSummary", "") or ""
        out.append(Job("ashby", company, j["title"], j.get("location", ""), j["jobUrl"], _dt(j.get("publishedAt")),
                       j.get("descriptionPlain", ""), remote=bool(j.get("isRemote")),
                       workplace=(j.get("workplaceType") or "").lower(), compensation=comp))
    return out


ENDPOINTS = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", parse_greenhouse),
    "lever": ("https://api.lever.co/v0/postings/{slug}?mode=json", parse_lever),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true", parse_ashby),
}


def fetch(ats: str, slug: str, company: str | None = None, timeout: int = 20) -> list[Job]:
    url, parser = ENDPOINTS[ats]
    req = urllib.request.Request(url.format(slug=slug), headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return parser(company or slug, data)
