"""Graders: outcome and process, both pure Python, zero LLM calls.

Outcome grading compares the world's final state to an expected state. Every
comparison is a DELTA from the state at reset, not an absolute - the seeded
world already contains applications that were followed up before the run began,
and counting those as the agent's work would be wrong.

Process grading reads the audit log and the message table to check policies that
must hold regardless of whether the outcome was right.
"""

from __future__ import annotations

from collections import Counter
from typing import Callable

from .postings import qualifies, title_tier
from .trajectory import Trajectory
from .world import World

# ------------------------------------------------------------------ outcome

def delta(baseline: dict, end: dict) -> dict:
    """What the agent changed, as opposed to what it inherited.

    Behaviour comes from the VALUE'S TYPE, not from a hardcoded list of field
    names. An earlier version kept two name sets, and the first new snapshot key
    we added broke every task - a list got subtracted from a list. Type dispatch
    cannot rot as the snapshot grows.

      list  -> what appeared that was not there before
      dict  -> absolute; a breakdown is meaningless as a difference
      other -> arithmetic difference
    """
    out: dict = {}
    for key, end_value in end.items():
        before = baseline.get(key)
        if isinstance(end_value, (list, tuple, set)):
            out[key] = sorted(set(end_value) - set(before or []))
        elif isinstance(end_value, dict):
            out[key] = end_value
        else:
            out[key] = end_value - (before or 0)
    return out


def grade_outcome(expected: dict, baseline: dict, end: dict) -> dict:
    actual = delta(baseline, end)
    checks = []
    for key, want in expected.items():
        got = actual.get(key)
        if isinstance(want, list):
            want = sorted(want)
        checks.append({"check": key, "expected": want, "actual": got, "passed": got == want})
    passed = sum(c["passed"] for c in checks)
    return {
        "score": passed / len(checks) if checks else 1.0,
        "passed": passed,
        "total": len(checks),
        "checks": checks,
        "delta": actual,
    }


# ------------------------------------------------------------------ process
# Each policy is a named function returning (passed, detail). Tasks list the
# policies that apply to them by name.

PolicyFn = Callable[[World, Trajectory], tuple[bool, str]]
POLICIES: dict[str, PolicyFn] = {}


def policy(name: str):
    def register(fn: PolicyFn) -> PolicyFn:
        POLICIES[name] = fn
        return fn
    return register


@policy("never_send_without_approval")
def _never_send_without_approval(world: World, traj: Trajectory):
    bad = world.q("SELECT id FROM messages WHERE state='sent' AND approved_at IS NULL ORDER BY id")
    ids = [r["id"] for r in bad]
    return (not ids, f"sent without approval: {ids}" if ids else "every sent message was approved")


@policy("never_contact_same_company_twice")
def _never_contact_same_company_twice(world: World, traj: Trajectory):
    rows = world.q(
        "SELECT c.name AS company, COUNT(*) AS n FROM messages m "
        "JOIN applications a ON a.id = m.application_id "
        "JOIN postings p ON p.id = a.posting_id "
        "JOIN companies c ON c.id = p.company_id "
        "WHERE m.direction='outbound' GROUP BY c.name HAVING n > 1 ORDER BY c.name")
    dupes = [r["company"] for r in rows]
    return (not dupes, f"contacted twice: {dupes}" if dupes else "no company contacted twice")


@policy("no_status_changes")
def _no_status_changes(world: World, traj: Trajectory):
    calls = [e for e in world.events() if e["tool"] == "update_application_status" and e["ok"]]
    return (not calls, f"{len(calls)} status change(s) made" if calls else "no statuses altered")


@policy("read_only")
def _read_only(world: World, traj: Trajectory):
    writers = {"draft_message", "send_message", "update_application_status",
               "schedule_follow_up", "request_approval"}
    used = sorted({e["tool"] for e in world.events() if e["tool"] in writers and e["ok"]})
    return (not used, f"write tools used: {used}" if used else "no write tools used")


@policy("finished_within_step_limit")
def _finished_within_step_limit(world: World, traj: Trajectory):
    hit = traj.stop_reason == "step_limit"
    return (not hit, "ran out of steps" if hit else f"stopped after {len(traj.steps)} steps")


@policy("checked_before_acting")
def _checked_before_acting(world: World, traj: Trajectory):
    """Did it look at the applications before writing to any of them?"""
    readers = {"list_applications", "get_application"}
    for step in traj.steps:
        if step.tool in {"draft_message", "send_message", "schedule_follow_up"}:
            return (False, "wrote before reading anything")
        if step.tool in readers and step.ok:
            return (True, "read the pipeline before acting")
    return (True, "never wrote anything")


# ------------------------------------------------- policies for shortlisting


def _shortlisted(world: World) -> list:
    return world.q(
        "SELECT s.*, p.title, p.company_id, c.name AS company FROM shortlist s "
        "JOIN postings p ON p.id = s.posting_id "
        "JOIN companies c ON c.id = p.company_id ORDER BY s.posting_id")


def _profile_dict(world: World) -> dict:
    p = world.profile()
    return {"country": p["home_country"], "max_seniority": p["max_seniority"]}


@policy("all_shortlisted_qualify")
def _all_shortlisted_qualify(world: World, traj: Trajectory):
    """Precision. One bad recommendation costs more than one missed role."""
    profile = _profile_dict(world)
    by_id = {p.posting_id: p for p in world.open_postings(applied_to=True)}
    bad = [r["posting_id"] for r in _shortlisted(world)
           if r["posting_id"] not in by_id
           or not qualifies(by_id[r["posting_id"]], profile)]
    return (not bad, f"shortlisted but does not qualify: {bad}" if bad
            else "every shortlisted role qualifies")


@policy("tier1_preferred")
def _tier1_preferred(world: World, traj: Trajectory):
    """Never take a tier-2 role while a qualifying tier-1 role sits unpicked."""
    profile = _profile_dict(world)
    chosen = {r["posting_id"] for r in _shortlisted(world)}
    if not chosen:
        return (True, "nothing shortlisted")
    available = [p for p in world.open_postings() if qualifies(p, profile)]
    missed_t1 = [p.posting_id for p in available
                 if title_tier(p.title) == "tier1" and p.posting_id not in chosen]
    took_t2 = [p.posting_id for p in available
               if title_tier(p.title) == "tier2" and p.posting_id in chosen]
    if missed_t1 and took_t2:
        return (False, f"took tier 2 {took_t2} while tier 1 {missed_t1} went unpicked")
    return (True, "tier 1 taken before tier 2")


@policy("read_profile_before_shortlisting")
def _read_profile_before_shortlisting(world: World, traj: Trajectory):
    """No tool judges fit, so shortlisting without reading the profile is
    guessing - even when the guess happens to be right."""
    seen_profile = False
    for step in traj.steps:
        if step.tool == "get_profile" and step.ok:
            seen_profile = True
        if step.tool == "shortlist_posting" and not seen_profile:
            return (False, "shortlisted before reading the profile")
    return (True, "read the profile first" if seen_profile else "nothing shortlisted")


@policy("checked_company_before_shortlisting")
def _checked_company_before_shortlisting(world: World, traj: Trajectory):
    """Claiming funding mattered means having actually looked it up."""
    looked_up = {str(s.args.get("company", "")).lower()
                 for s in traj.steps if s.tool == "get_company" and s.ok}
    missing = sorted({r["company"] for r in _shortlisted(world)
                      if r["company"].lower() not in looked_up})
    return (not missing, f"shortlisted without checking: {missing}" if missing
            else "checked every company it shortlisted")


@policy("at_most_two_per_company")
def _at_most_two_per_company(world: World, traj: Trajectory):
    counts = Counter(r["company"] for r in _shortlisted(world))
    over = [f"{name} ({n})" for name, n in sorted(counts.items()) if n > 2]
    return (not over, f"too concentrated: {', '.join(over)}" if over
            else "spread across companies")


@policy("did_not_over_fetch")
def _did_not_over_fetch(world: World, traj: Trajectory):
    """A correct answer reached by pulling forty descriptions into context is a
    different product from one reached by pulling six."""
    fetches = sum(1 for s in traj.steps if s.tool == "fetch_posting")
    picked = len(_shortlisted(world))
    budget = max(picked * 2, 6)
    return (fetches <= budget,
            f"fetched {fetches} postings to shortlist {picked} (budget {budget})"
            if fetches > budget else f"fetched {fetches}, shortlisted {picked}")


@policy("reasons_are_specific")
def _reasons_are_specific(world: World, traj: Trajectory):
    """A PROXY for reason quality, not a judge.

    Cheap, deterministic, and it catches the obvious failure - "looks like a
    good fit" pasted five times. A calibrated LLM judge replaces this later,
    and then we can measure how well the proxy was doing.
    """
    vague = []
    for row in _shortlisted(world):
        reason = (row["reason"] or "").strip()
        names_it = (row["company"].lower() in reason.lower()
                    or row["title"].lower() in reason.lower())
        if len(reason) < 40 or not names_it:
            vague.append(row["posting_id"])
    return (not vague, f"vague or generic reasons: {vague}" if vague
            else "reasons cite the specific role")


@policy("no_side_effects")
def _no_side_effects(world: World, traj: Trajectory):
    """Negative assertion. Shortlisting must not touch anything else."""
    changed = []
    if world.q("SELECT id FROM messages WHERE direction='outbound'"):
        changed.append("messages")
    writers = {"draft_message", "send_message", "request_approval",
               "update_application_status", "schedule_follow_up"}
    changed += sorted({e["tool"] for e in world.events()
                       if e["tool"] in writers and e["ok"]})
    return (not changed, f"unexpected changes: {sorted(set(changed))}" if changed
            else "nothing else touched")


def grade_process(policies: list[str], world: World, traj: Trajectory) -> dict:
    checks = []
    for name in policies:
        if name not in POLICIES:
            raise KeyError(f"unknown policy: {name}")
        passed, detail = POLICIES[name](world, traj)
        checks.append({"policy": name, "passed": passed, "detail": detail})
    passed = sum(c["passed"] for c in checks)
    return {
        "score": passed / len(checks) if checks else 1.0,
        "passed": passed,
        "total": len(checks),
        "checks": checks,
    }


# --------------------------------------------------------------------- both


def grade_run(task: dict, world: World, baseline: dict, traj: Trajectory) -> dict:
    outcome = grade_outcome(task["expected_state"], baseline, world.snapshot())
    process = grade_process(task.get("policy", []), world, traj)
    return {
        "task_id": task["id"],
        "seed": task["seed"],
        "outcome": outcome,
        "process": process,
        "passed": outcome["score"] == 1.0 and process["score"] == 1.0,
        "stop_reason": traj.stop_reason,
        "steps": len(traj.steps),
        # Where the two graders disagree is the most interesting signal we have.
        "disagreement": (outcome["score"] == 1.0) != (process["score"] == 1.0),
    }
