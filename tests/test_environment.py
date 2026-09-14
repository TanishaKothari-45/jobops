"""What must stay true. These run in under a second and need no network."""

from __future__ import annotations

import hashlib
import json

import pytest

from jobops.clock import days_between
from jobops.reference import AGENTS
from jobops.runner import run_suite, summarise
from jobops.seed import WorldSetup
from jobops.tasks import TASKS, held_out, training
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


def test_reference_agent_passes_every_task():
    reports = run_suite(AGENTS["reference"], TASKS)
    failed = [r["task_id"] for r in reports if not r["passed"]]
    assert failed == [], f"reference agent failed: {failed}"


def test_overeager_agent_fails_on_outcome():
    reports = run_suite(AGENTS["overeager"], training())
    assert summarise(reports)["passed"] == 0


def test_hacker_agent_is_caught_by_the_approval_policy():
    report = run_suite(AGENTS["hacker"], [t for t in TASKS if t["id"] == "t01_follow_up_stale"])[0]
    violations = [c for c in report["process"]["checks"]
                  if c["policy"] == "never_send_without_approval" and not c["passed"]]
    assert violations, "approval policy did not fire"


def test_suite_is_reproducible():
    def scores():
        return [(r["task_id"], r["outcome"]["score"], r["process"]["score"])
                for r in run_suite(AGENTS["reference"], TASKS)]
    assert scores() == scores()


def test_held_out_slice_exists_and_is_separate():
    assert len(held_out()) == 2
    assert set(t["id"] for t in held_out()).isdisjoint(t["id"] for t in training())


def test_every_task_has_a_negative_assertion_or_policy():
    for task in TASKS:
        negatives = [k for k, v in task["expected_state"].items() if v in (0, [])]
        assert negatives or task["policy"], f"{task['id']} asserts nothing negative"
