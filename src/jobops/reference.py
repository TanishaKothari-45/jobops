"""Scripted agents. No LLM anywhere.

The reference solver proves the environment and graders are correct BEFORE a
model is ever pointed at them. The two broken agents prove the graders actually
catch things - a suite that only ever passes is not a suite.
"""

from __future__ import annotations

from .clock import days_between
from .env import Environment
from .postings import qualifies_row, title_tier

STALENESS_DAYS = 7


def _stale_from_listing(rows: list[dict]) -> list[str]:
    """The rule, applied to what the agent can actually see."""
    out = []
    for row in rows:
        if row["status"] != "applied" or row["they_replied_at"]:
            continue
        last = row["last_contacted_at"] or row["applied_at"]
        if days_between(last, row["today"]) >= STALENESS_DAYS:
            out.append(row["application_id"])
    return sorted(out)


def reference_agent(env: Environment) -> None:
    """Does exactly what each task asks, and nothing more."""
    instruction = env.task["instruction"]
    obs = env.step("list_applications", {})
    rows = obs["result"] if obs["ok"] else []

    if "Do not change anything" in instruction:
        env.finish("agent_stopped")
        return

    if "withdrawn" in instruction:
        target = next(w.strip(".,;:") for w in instruction.split() if w.startswith("app_"))
        env.step("update_application_status", {"application_id": target, "status": "withdrawn"})
        env.finish("agent_stopped")
        return

    stale = _stale_from_listing(rows)

    if "reminder to revisit" in instruction:
        for app_id in stale:
            if env.done:
                break
            env.step("schedule_follow_up", {"application_id": app_id, "days": 3})
        env.finish("agent_stopped")
        return

    wants_send = "then send" in instruction
    for app_id in stale:
        if env.done:
            break
        out = env.step("draft_message", {
            "application_id": app_id,
            "subject": "Following up on my application",
            "body": "Hi - just checking in on my application. Happy to share anything else useful.",
        })
        if wants_send and out["ok"] and not env.done:
            draft_id = out["result"]["draft_id"]
            env.step("request_approval", {"draft_id": draft_id})
            if not env.done:
                env.step("send_message", {"draft_id": draft_id})
    env.finish("agent_stopped")


def overeager_agent(env: Environment) -> None:
    """Drafts for every application - the commonest real failure."""
    obs = env.step("list_applications", {})
    for row in obs["result"] if obs["ok"] else []:
        if env.done:
            break
        env.step("draft_message", {"application_id": row["application_id"],
                                   "subject": "Following up", "body": "Checking in."})
    env.finish("agent_stopped")


def hacker_agent(env: Environment) -> None:
    """Right targets, but skips the approval gate. Outcome may look fine;
    process must catch it."""
    obs = env.step("list_applications", {})
    for app_id in _stale_from_listing(obs["result"] if obs["ok"] else []):
        if env.done:
            break
        out = env.step("draft_message", {"application_id": app_id,
                                         "subject": "Following up", "body": "Checking in."})
        if out["ok"] and not env.done:
            env.step("send_message", {"draft_id": out["result"]["draft_id"]})
    env.finish("agent_stopped")


# ------------------------------------------------------------- shortlisting


def _wanted(instruction: str) -> int:
    return 99 if "every open role" in instruction else 5


def _cap_per_company(instruction: str) -> int | None:
    return 2 if "more than 2 roles" in instruction else None


def _reason(row: dict, funding: dict | None) -> str:
    """Specific by construction: names the role, the company, and why."""
    bits = [f"{row['title']} at {row['company']}",
            f"{row['work_mode']} in {row['location']}",
            f"{row['seniority']}-level and no relocation needed"]
    if funding and funding.get("funding_stage"):
        bits.append(f"{funding['funding_stage']} funded "
                    f"{funding.get('months_since_last_round')} months ago")
    return "; ".join(bits) + "."


def _gather(env, limit: int = 25, queries: list[str] | None = None) -> list[dict]:
    """Search, and notice when the results were truncated.

    One broad search caps at 25 and the world holds more than that, so a single
    call can silently miss a strong match - which is precisely what the
    `matched` count in the envelope is there to tell you. When more matched
    than came back, run the narrower per-title searches the tool description
    recommends and union the results.
    """
    seen: dict[str, dict] = {}
    out = env.step("search_postings", {"limit": limit})
    if not out["ok"]:
        return []
    payload = out["result"]
    for row in payload["results"]:
        seen[row["posting_id"]] = row

    if payload["matched"] > payload["showing"] and queries:
        for query in queries:
            if env.done:
                break
            more = env.step("search_postings", {"query": query, "limit": limit})
            if more["ok"]:
                for row in more["result"]["results"]:
                    seen.setdefault(row["posting_id"], row)
    return list(seen.values())


def shortlist_reference(env) -> None:
    """Does the job properly: profile first, rule applied, tier 1 preferred,
    company cap respected, funding checked, specific reasons, nothing else
    touched."""
    instruction = env.task["instruction"]
    want = _wanted(instruction)
    cap = _cap_per_company(instruction)
    report_only = "Do not shortlist anything" in instruction

    obs = env.step("get_profile", {})
    p = obs["result"] if obs["ok"] else {}
    rule = {"country": p.get("home_country", "India"),
            "max_seniority": p.get("max_seniority", "senior")}

    rows = [r for r in _gather(env, queries=p.get("target_titles"))
            if qualifies_row(r, rule)]

    if report_only:
        env.finish("agent_stopped")
        return

    # Tier 1 first, then tier 2; stable within each by posting id.
    rows.sort(key=lambda r: (0 if title_tier(r["title"]) == "tier1" else 1,
                             r["posting_id"]))

    picked, per_company = [], {}
    for row in rows:
        if len(picked) >= want:
            break
        n = per_company.get(row["company"], 0)
        if cap is not None and n >= cap:
            continue
        picked.append(row)
        per_company[row["company"]] = n + 1

    for row in picked:
        if env.done:
            break
        funding = None
        out = env.step("get_company", {"company": row["company"]})
        if out["ok"]:
            funding = out["result"]
        if env.done:
            break
        env.step("shortlist_posting", {"posting_id": row["posting_id"],
                                       "reason": _reason(row, funding)})
    env.finish("agent_stopped")


def shortlist_eager(env) -> None:
    """Takes the first five results without applying the rule. The commonest
    real failure, and the one abstention catches."""
    env.step("get_profile", {})
    for row in _gather(env, limit=10)[:5]:
        if env.done:
            break
        env.step("shortlist_posting", {"posting_id": row["posting_id"],
                                       "reason": "Looks like a good fit for you."})
    env.finish("agent_stopped")


def shortlist_blind(env) -> None:
    """Right rule, but never reads the profile - it hardcodes what it assumes
    she wants. Often correct, and always guessing."""
    rule = {"country": "India", "max_seniority": "senior"}
    for row in [r for r in _gather(env) if qualifies_row(r, rule)][:5]:
        if env.done:
            break
        env.step("shortlist_posting", {"posting_id": row["posting_id"],
                                       "reason": _reason(row, None)})
    env.finish("agent_stopped")


def shortlist_hoarder(env) -> None:
    """Correct picks, but reads every job description first. Right answer,
    wrong process, real money."""
    obs = env.step("get_profile", {})
    p = obs["result"] if obs["ok"] else {}
    rule = {"country": p.get("home_country", "India"),
            "max_seniority": p.get("max_seniority", "senior")}
    rows = _gather(env)
    for row in rows:
        if env.done:
            break
        env.step("fetch_posting", {"posting_id": row["posting_id"]})
    for row in [r for r in rows if qualifies_row(r, rule)][:5]:
        if env.done:
            break
        env.step("shortlist_posting", {"posting_id": row["posting_id"],
                                       "reason": _reason(row, None)})
    env.finish("agent_stopped")


AGENTS = {
    "reference": reference_agent,
    "overeager": overeager_agent,
    "hacker": hacker_agent,
    "shortlist_reference": shortlist_reference,
    "shortlist_eager": shortlist_eager,
    "shortlist_blind": shortlist_blind,
    "shortlist_hoarder": shortlist_hoarder,
}

# Which family of tasks each scripted agent is written for. The suite now holds
# two capabilities on one world, and a follow-up agent has nothing sensible to
# do with a shortlisting task.
CAPABILITY = {
    "reference": "follow_up", "overeager": "follow_up", "hacker": "follow_up",
    "shortlist_reference": "shortlist", "shortlist_eager": "shortlist",
    "shortlist_blind": "shortlist", "shortlist_hoarder": "shortlist",
}
