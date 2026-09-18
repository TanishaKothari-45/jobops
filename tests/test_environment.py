"""What must stay true. These run in under a second and need no network."""

from __future__ import annotations

import hashlib
import json

import pytest

from jobops.clock import days_between
from jobops.env import Environment
from jobops.reference import AGENTS
from jobops.runner import run_suite, summarise
from jobops.seed import WorldSetup
from jobops.tasks import TASKS, by_id, held_out, training
from jobops.world import World


def fingerprint(seed: int) -> str:
    w = World(seed, WorldSetup())
    rows = [tuple(r) for t in ("companies", "postings", "applications", "messages")
            for r in w.q(f"SELECT * FROM {t} ORDER BY 1")]
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()


def test_same_seed_builds_identical_world():
    assert fingerprint(42) == fingerprint(42)


def test_different_seeds_build_different_worlds():
    assert fingerprint(42) != fingerprint(43)


def test_world_clock_is_frozen():
    assert World(42, WorldSetup()).now() == World(42, WorldSetup()).now()


@pytest.mark.parametrize("seed", [42, 43, 44, 101])
def test_stale_rule_matches_requested_count(seed):
    setup = WorldSetup(stale=3, replied=2, followed_recently=2, fresh=3)
    assert len(World(seed, setup).stale_application_ids()) == setup.stale


def test_stale_rule_excludes_applications_that_replied():
    w = World(42, WorldSetup())
    for app_id in w.stale_application_ids():
        row = w.one("SELECT * FROM applications WHERE id = ?", (app_id,))
        assert row["last_inbound_at"] is None
        assert days_between(row["last_outbound_at"], w.now()) >= 7


def of(capability: str) -> list[dict]:
    return [t for t in TASKS if t["capability"] == capability]


def test_reference_agent_passes_every_follow_up_task():
    reports = run_suite(AGENTS["reference"], of("follow_up"))
    failed = [r["task_id"] for r in reports if not r["passed"]]
    assert failed == [], f"reference agent failed: {failed}"


def test_reference_shortlister_passes_every_shortlist_task():
    reports = run_suite(AGENTS["shortlist_reference"], of("shortlist"))
    failed = [r["task_id"] for r in reports if not r["passed"]]
    assert failed == [], f"reference shortlister failed: {failed}"


def test_overeager_agent_fails_on_outcome():
    follow_up = [t for t in training() if t["capability"] == "follow_up"]
    reports = run_suite(AGENTS["overeager"], follow_up)
    assert summarise(reports)["passed"] == 0


def test_hacker_agent_is_caught_by_the_approval_policy():
    report = run_suite(AGENTS["hacker"], [t for t in TASKS if t["id"] == "t01_follow_up_stale"])[0]
    violations = [c for c in report["process"]["checks"]
                  if c["policy"] == "never_send_without_approval" and not c["passed"]]
    assert violations, "approval policy did not fire"


def test_suite_is_reproducible():
    def scores():
        return [(r["task_id"], r["outcome"]["score"], r["process"]["score"])
                for r in run_suite(AGENTS["reference"], of("follow_up"))]
    assert scores() == scores()


# ------------------------------------------------------ the shortlisting suite


def test_target_titles_cover_every_tier1_keyword():
    """Two definitions of "worth applying to" - the grader's TIER1 keywords and
    the profile's target_titles - must not drift apart. They did once: the
    grader punished the agent for missing a Research Engineer role the profile
    never told it to look for.
    """
    from jobops.postings import TIER1

    titles = " ".join(World(42, WorldSetup()).profile()["target_titles"]).lower()
    missing = [k for k in TIER1 if k not in titles and k not in ("evals", "mts")]
    assert missing == [], f"tier-1 keywords no target title covers: {missing}"


def test_abstention_world_really_has_nothing_to_pick():
    """s03 is only a test of over-eagerness if the world genuinely offers
    plenty to look at and nothing worth taking."""
    from jobops.postings import qualifies
    from jobops.tasks.catalog import EXCLUDED_TITLES

    w = World(42, WorldSetup(only_titles=EXCLUDED_TITLES))
    postings = w.open_postings()
    rule = {"country": "India", "max_seniority": "senior"}
    assert len(postings) >= 20, "should have plenty to read"
    assert [p.posting_id for p in postings if qualifies(p, rule)] == []


def test_permutation_pair_shares_one_right_answer():
    natural = by_id("s07_order_natural")
    reversed_ = by_id("s08_order_reversed")
    assert natural["expected_state"] == reversed_["expected_state"]
    assert natural["instruction"] == reversed_["instruction"]
    assert len(natural["expected_state"]["shortlisted"]) == 3


def test_reference_shortlister_is_order_invariant():
    """The permutation test itself: same world, results served in opposite
    order, and the shortlist must not move."""
    def picks(task_id):
        env = Environment(by_id(task_id))
        env.reset()
        AGENTS["shortlist_reference"](env)
        return sorted(env.world.snapshot()["shortlisted"])

    assert picks("s07_order_natural") == picks("s08_order_reversed")


@pytest.mark.parametrize("agent,task_id,policy_name", [
    ("shortlist_eager", "s01_shortlist_five", "all_shortlisted_qualify"),
    ("shortlist_eager", "s01_shortlist_five", "reasons_are_specific"),
    ("shortlist_blind", "s01_shortlist_five", "read_profile_before_shortlisting"),
    ("shortlist_hoarder", "s01_shortlist_five", "did_not_over_fetch"),
])
def test_each_broken_shortlister_trips_its_policy(agent, task_id, policy_name):
    """A suite that only ever passes is not a suite."""
    report = run_suite(AGENTS[agent], [by_id(task_id)])[0]
    tripped = [c["policy"] for c in report["process"]["checks"] if not c["passed"]]
    assert policy_name in tripped, f"{agent} did not trip {policy_name}; tripped {tripped}"


def test_eager_shortlister_fails_abstention():
    """The single most important negative test: asked for five when none
    qualify, it must not invent five."""
    report = run_suite(AGENTS["shortlist_eager"], [by_id("s03_nothing_qualifies")])[0]
    assert not report["passed"]
    sizes = [c for c in report["outcome"]["checks"] if c["check"] == "shortlist_size"]
    assert sizes and sizes[0]["actual"] > 0


def test_held_out_slice_exists_and_is_separate():
    """Roughly a fifth of every capability stays unread while we iterate. A
    proportion rather than a count, so adding tasks cannot silently erode it."""
    assert set(t["id"] for t in held_out()).isdisjoint(t["id"] for t in training())
    for capability in {t["capability"] for t in TASKS}:
        total = [t for t in TASKS if t["capability"] == capability]
        kept = [t for t in total if t.get("held_out")]
        assert len(kept) >= max(1, len(total) // 6), (
            f"{capability}: only {len(kept)} of {len(total)} held out")


def test_every_task_has_a_negative_assertion_or_policy():
    for task in TASKS:
        negatives = [k for k, v in task["expected_state"].items() if v in (0, [])]
        assert negatives or task["policy"], f"{task['id']} asserts nothing negative"
