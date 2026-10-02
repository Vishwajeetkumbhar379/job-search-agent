"""jobscout: discover, evaluate and rank live jobs; lint application text.

  jobscout run --config config.toml
  jobscout lint cover_letter.txt --kind cover_letter
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from .evaluate import Profile, evaluate, is_target
from .humanizer import lint, word_count_ok
from .sources import ENDPOINTS, fetch


def _offline(folder: str):
    """Yield (company, jobs) from saved API responses named <ats>__<Company>.json."""
    import json

    for f in sorted(Path(folder).glob("*__*.json")):
        ats, company = f.stem.split("__", 1)
        yield company, ENDPOINTS[ats][1](company, json.loads(f.read_text(encoding="utf-8")))


def cmd_run(a) -> int:
    cfg = tomllib.loads(Path(a.config).read_text(encoding="utf-8"))
    p = Profile.from_dict(cfg["profile"])
    exclude = cfg.get("filters", {}).get("exclude_titles", [])
    seen, evals = set(), []

    def boards():
        if a.offline:
            yield from (jobs for _, jobs in _offline(a.offline))
            return
        for b in cfg["boards"]:
            try:
                yield fetch(b["ats"], b["slug"], b.get("company"))
            except Exception as e:  # one dead board shouldn't stop the run
                print(f"  ! {b['slug']}: {e}", file=sys.stderr)

    for jobs in boards():
        for j in jobs:
            if j.key in seen or not is_target(j, p, exclude):
                continue
            seen.add(j.key)
            evals.append(evaluate(j, p))
    evals.sort(key=lambda e: -e.score)
    lines = ["| Score | Band | Lane | Role | Company | Link |", "|---:|---|---|---|---|---|"]
    lines += [f"| {e.score} | {e.band} | {e.lane} | {e.job.title} | {e.job.company} | [open]({e.job.url}) |" for e in evals]
    for e in evals:
        lines += ["", f"### {e.job.title} · {e.job.company} · {e.score}/100", ""]
        lines += [f"- {r.importance} · {r.evidence} · **{r.match}** · {r.text}" + (f" ({r.proof})" if r.proof else "") for r in e.requirements]
        lines += [f"- Blocker: {b}" for b in e.blockers] + [f"- Note: {n}" for n in e.notes]
    report = "\n".join(lines)
    Path(a.out).write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n{len(evals)} matching roles · {sum(e.score >= 80 for e in evals)} at 80+ · saved to {a.out}")
    return 0


def cmd_lint(a) -> int:
    text = Path(a.file).read_text(encoding="utf-8")
    issues = lint(text)
    for i in issues:
        print(i)
    if a.kind:
        ok, msg = word_count_ok(text, a.kind)
        print(("OK  " if ok else "FIX ") + msg)
    print(f"\n{len(issues)} issue(s)")
    return 1 if issues else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jobscout")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="Scan boards and rank matching jobs")
    r.add_argument("--config", default="config.toml")
    r.add_argument("--out", default="shortlist.md")
    r.add_argument("--offline", metavar="FOLDER", help="Read saved API responses instead of fetching (demo mode)")
    r.set_defaults(fn=cmd_run)
    l = sub.add_parser("lint", help="Check application text for AI-writing tells")
    l.add_argument("file")
    l.add_argument("--kind", choices=["email", "cover_letter", "follow_up", "connection_note"])
    l.set_defaults(fn=cmd_lint)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
