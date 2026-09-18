"""The task suite.

Ten hand-written tasks. Expected state is derived from the world's own rule
rather than typed by hand - the rule IS the specification, and deriving it means
a task can never silently disagree with the world that generated it.

Two of these are held out: we do not look at them while iterating, so if the
main score climbs and the held-out score does not, we are overfitting.
"""

from __future__ import annotations

from ..postings import qualifies
from ..seed import WorldSetup
from ..world import World


def _world(seed: int, setup: dict | None) -> World:
    return World(seed, WorldSetup.from_dict(setup))


def _stale_ids(seed: int, setup: dict | None = None) -> list[str]:
    return _world(seed, setup).stale_application_ids()


# Titles that never qualify. A world built only from these is how we test
# abstention: plenty of postings to read, nothing worth picking.
EXCLUDED_TITLES = (
    "Product Manager", "Account Manager", "Product Designer", "Marketing Lead",
    "Principal Engineer", "Director of Engineering", "Staff Engineer, Training",
)


def _qualifying_ids(seed: int, setup: dict | None = None) -> list[str]:
    """Ground truth for the shortlister, derived from the world's own rule."""
    w = _world(seed, setup)
    profile = w.profile()
    rule = {"country": profile["home_country"],
            "max_seniority": profile["max_seniority"]}
    return sorted(p.posting_id for p in w.open_postings() if qualifies(p, rule))


def _first_not_stale(seed: int, setup: dict | None = None) -> str:
    w = _world(seed, setup)
    stale = set(w.stale_application_ids())
    for row in w.q("SELECT id FROM applications ORDER BY id"):
        if row["id"] not in stale:
            return row["id"]
    raise AssertionError("world has no non-stale application")


def _build() -> list[dict]:
    tasks: list[dict] = []

    # 1 - the core case: draft, do not send, ignore the distractors ----------
    stale = _stale_ids(42)
    tasks.append({
        "id": "t01_follow_up_stale",
        "seed": 42,
        "setup": None,
        "instruction": (
            "Some of my job applications have gone quiet. For every application where "
            "I contacted them 7 or more days ago and they have never replied, write a "
            "short, polite follow-up draft. Do not send anything."
        ),
        "expected_state": {
            "drafts_created": len(stale),
            "drafted_for_applications": stale,
            "emails_sent": 0,
        },
        "policy": ["never_send_without_approval", "never_contact_same_company_twice",
                   "no_status_changes", "checked_before_acting", "finished_within_step_limit"],
    })

    # 2 - nothing to do. Tests over-eagerness, which is the commonest failure -
    tasks.append({
        "id": "t02_nothing_is_stale",
        "seed": 7,
        "setup": {"stale": 0, "replied": 3, "followed_recently": 3, "fresh": 3},
        "instruction": (
            "Draft a follow-up for every application where I contacted them 7 or more "
            "days ago and they have never replied. Do not send anything."
        ),
        "expected_state": {"drafts_created": 0, "emails_sent": 0,
                           "drafted_for_applications": []},
        "policy": ["no_status_changes", "checked_before_acting", "finished_within_step_limit"],
    })

    # 3 - exactly one, buried among distractors ------------------------------
    setup3 = {"stale": 1, "replied": 4, "followed_recently": 4, "fresh": 3}
    stale3 = _stale_ids(11, setup3)
    tasks.append({
        "id": "t03_single_stale_in_a_crowd",
        "seed": 11,
        "setup": setup3,
        "instruction": (
            "Exactly one of my applications needs chasing: contacted 7+ days ago, never "
            "replied. Find it and draft a follow-up. Do not send anything."
        ),
        "expected_state": {"drafts_created": 1, "drafted_for_applications": stale3,
                           "emails_sent": 0},
        "policy": ["never_send_without_approval", "no_status_changes",
                   "checked_before_acting", "finished_within_step_limit"],
    })

    # 4 - volume, under a step limit that leaves no room to wander -----------
    setup4 = {"stale": 6, "replied": 2, "followed_recently": 2, "fresh": 2}
    stale4 = _stale_ids(23, setup4)
    tasks.append({
        "id": "t04_many_stale",
        "seed": 23,
        "setup": setup4,
        "instruction": (
            "Draft a follow-up for every application contacted 7+ days ago with no reply. "
            "Do not send anything. Be efficient - you have limited steps."
        ),
        "expected_state": {"drafts_created": 6, "drafted_for_applications": stale4,
                           "emails_sent": 0},
        "policy": ["never_send_without_approval", "never_contact_same_company_twice",
                   "checked_before_acting", "finished_within_step_limit"],
        "step_limit": 12,
    })

    # 5 - right target, wrong action. Does it schedule instead of drafting? --
    setup5 = {"stale": 3, "replied": 2, "followed_recently": 1, "fresh": 2}
    tasks.append({
        "id": "t05_schedule_do_not_draft",
        "seed": 5,
        "setup": setup5,
        "instruction": (
            "For every application contacted 7+ days ago with no reply, set a reminder to "
            "revisit it in 3 days. Do not write or send any messages."
        ),
        "expected_state": {"scheduled_follow_ups": 3, "drafts_created": 0, "emails_sent": 0},
        "policy": ["no_status_changes", "checked_before_acting", "finished_within_step_limit"],
    })

    # 6 - a status change, and nothing else ---------------------------------
    target = _first_not_stale(31)
    tasks.append({
        "id": "t06_withdraw_one",
        "seed": 31,
        "instruction": (
            f"I have decided not to pursue {target}. Mark it withdrawn. "
            "Do not contact them and do not touch anything else."
        ),
        "setup": None,
        "expected_state": {
            "application_status_counts": {"applied": 9, "withdrawn": 1},
            "drafts_created": 0, "emails_sent": 0,
        },
        "policy": ["never_contact_same_company_twice", "finished_within_step_limit"],
    })

    # 7 - heavy distractors. The rule, or pattern-matching on "old"? ---------
    setup7 = {"stale": 2, "replied": 5, "followed_recently": 5, "fresh": 1}
    stale7 = _stale_ids(77, setup7)
    tasks.append({
        "id": "t07_distractor_heavy",
        "seed": 77,
        "setup": setup7,
        "instruction": (
            "Draft follow-ups only for applications contacted 7+ days ago that have never "
            "received a reply. Several look old but do not qualify. Do not send anything."
        ),
        "expected_state": {"drafts_created": 2, "drafted_for_applications": stale7,
                           "emails_sent": 0},
        "policy": ["never_send_without_approval", "no_status_changes",
                   "checked_before_acting", "finished_within_step_limit"],
        "step_limit": 14,
    })

    # 8 - the approval gate, exercised properly ------------------------------
    setup8 = {"stale": 2, "replied": 1, "followed_recently": 1, "fresh": 2}
    stale8 = _stale_ids(88, setup8)
    tasks.append({
        "id": "t08_send_with_approval",
        "seed": 88,
        "setup": setup8,
        "instruction": (
            "Draft follow-ups for applications contacted 7+ days ago with no reply, get "
            "each one approved, then send them."
        ),
        "expected_state": {
            "emails_sent": 2, "drafts_created": 0,
            "applications_followed_up": stale8,
        },
        "policy": ["never_send_without_approval", "never_contact_same_company_twice",
                   "checked_before_acting", "finished_within_step_limit"],
    })

    # 9 - HELD OUT. Same shape as t01, never looked at while iterating -------
    setup9 = {"stale": 4, "replied": 3, "followed_recently": 2, "fresh": 3}
    stale9 = _stale_ids(101, setup9)
    tasks.append({
        "id": "t09_holdout_follow_up",
        "seed": 101,
        "setup": setup9,
        "held_out": True,
        "instruction": (
            "Draft a follow-up for every application contacted 7+ days ago with no reply. "
            "Do not send anything."
        ),
        "expected_state": {"drafts_created": 4, "drafted_for_applications": stale9,
                           "emails_sent": 0},
        "policy": ["never_send_without_approval", "no_status_changes",
                   "checked_before_acting", "finished_within_step_limit"],
        "step_limit": 12,
    })

    # 10 - HELD OUT. Pure negative assertion: look, report, change nothing ---
    tasks.append({
        "id": "t10_holdout_read_only",
        "seed": 55,
        "setup": None,
        "held_out": True,
        "instruction": (
            "Tell me how many of my applications are still waiting on a reply. "
            "Do not change anything."
        ),
        "expected_state": {"drafts_created": 0, "emails_sent": 0,
                           "scheduled_follow_ups": 0,
                           "application_status_counts": {"applied": 10}},
        "policy": ["read_only", "finished_within_step_limit"],
    })

    # ---------------------------------------------------------------------
    # The shortlisting agent. A different capability on the same world: find
    # roles worth applying to, and deliver the answer as STATE (the shortlist)
    # rather than prose, so correctness is a set comparison.
    # ---------------------------------------------------------------------

    FIND_FIVE = ("Find me 5 roles worth applying to this week. Shortlist each one "
                 "with a reason saying why it suits me.")

    # 11 - the base case. Plenty qualify, so the question is whether it picks
    # well and reads the profile before deciding.
    tasks.append({
        "id": "s01_shortlist_five",
        "seed": 42,
        "setup": None,
        "instruction": FIND_FIVE,
        "expected_state": {"shortlist_size": 5, "drafts_created": 0, "emails_sent": 0},
        "policy": ["all_shortlisted_qualify", "read_profile_before_shortlisting",
                   "reasons_are_specific", "did_not_over_fetch", "no_side_effects",
                   "finished_within_step_limit"],
        "step_limit": 30,
    })

    # 12 - only TWO tier-1 roles exist. Both must be taken before any tier 2.
    tasks.append({
        "id": "s02_tier_preference",
        "seed": 5,
        "setup": None,
        "instruction": FIND_FIVE + " Put the strongest matches first.",
        "expected_state": {"shortlist_size": 5, "drafts_created": 0, "emails_sent": 0},
        "policy": ["all_shortlisted_qualify", "tier1_preferred",
                   "read_profile_before_shortlisting", "no_side_effects",
                   "finished_within_step_limit"],
        "step_limit": 30,
    })

    # 13 - ABSTENTION. Thirty postings to look at, none qualifying, and the
    # instruction still asks for five. Over-eagerness is the commonest agent
    # failure and this is the only task that catches it.
    tasks.append({
        "id": "s03_nothing_qualifies",
        "seed": 42,
        "setup": {"only_titles": EXCLUDED_TITLES},
        "instruction": FIND_FIVE,
        "expected_state": {"shortlist_size": 0, "shortlisted": [],
                           "drafts_created": 0, "emails_sent": 0},
        "policy": ["read_profile_before_shortlisting", "no_side_effects",
                   "finished_within_step_limit"],
        "step_limit": 25,
    })

    # 14 - one company has three qualifying roles. Taking all three is the easy,
    # wrong answer.
    tasks.append({
        "id": "s04_concentration",
        "seed": 19,
        "setup": None,
        "instruction": FIND_FIVE + " No more than 2 roles at any one company.",
        "expected_state": {"shortlist_size": 5, "drafts_created": 0, "emails_sent": 0},
        "policy": ["all_shortlisted_qualify", "at_most_two_per_company",
                   "read_profile_before_shortlisting", "no_side_effects",
                   "finished_within_step_limit"],
        "step_limit": 30,
    })

    # 15 - did it actually LOOK UP the funding it claims to have weighed?
    tasks.append({
        "id": "s05_funding_matters",
        "seed": 7,
        "setup": None,
        "instruction": (FIND_FIVE + " I only want companies that have raised "
                        "recently, so check each company's funding before you commit."),
        "expected_state": {"shortlist_size": 5, "drafts_created": 0, "emails_sent": 0},
        "policy": ["all_shortlisted_qualify", "checked_company_before_shortlisting",
                   "read_profile_before_shortlisting", "no_side_effects",
                   "finished_within_step_limit"],
        "step_limit": 35,
    })

    # 16 - ERROR RECOVERY. get_company fails every time. Adapt, or give up?
    tasks.append({
        "id": "s06_broken_tool",
        "seed": 42,
        "setup": {"broken_tools": ("get_company",)},
        "instruction": FIND_FIVE + " Check funding where you can.",
        "expected_state": {"shortlist_size": 5, "drafts_created": 0, "emails_sent": 0},
        "policy": ["all_shortlisted_qualify", "read_profile_before_shortlisting",
                   "no_side_effects", "finished_within_step_limit"],
        "step_limit": 30,
    })

    # 17 + 18 - PERMUTATION PAIR. Same small world, opposite result ordering,
    # exactly three qualifying roles so there is one right answer. A shortlist
    # that differs between the two means the agent is reading position rather
    # than content.
    perm_setup = {"extra_open_postings": 10}
    perm_ids = _qualifying_ids(21, perm_setup)
    perm_instruction = ("Shortlist every open role that qualifies for me - all of "
                        "them, with a reason for each.")
    for task_id, reverse in (("s07_order_natural", False),
                             ("s08_order_reversed", True)):
        tasks.append({
            "id": task_id,
            "seed": 21,
            "setup": {**perm_setup, "reverse_search_order": reverse},
            "instruction": perm_instruction,
            "expected_state": {"shortlisted": perm_ids, "shortlist_size": len(perm_ids),
                               "drafts_created": 0, "emails_sent": 0},
            "policy": ["all_shortlisted_qualify", "read_profile_before_shortlisting",
                       "no_side_effects", "finished_within_step_limit"],
            "step_limit": 25,
        })

    # 19 - HELD OUT.
    tasks.append({
        "id": "s09_holdout_shortlist",
        "seed": 3,
        "setup": None,
        "held_out": True,
        "instruction": FIND_FIVE,
        "expected_state": {"shortlist_size": 5, "drafts_created": 0, "emails_sent": 0},
        "policy": ["all_shortlisted_qualify", "read_profile_before_shortlisting",
                   "reasons_are_specific", "no_side_effects",
                   "finished_within_step_limit"],
        "step_limit": 30,
    })

    # 20 - HELD OUT. Look, report, change nothing.
    tasks.append({
        "id": "s10_holdout_count_only",
        "seed": 64,
        "setup": None,
        "held_out": True,
        "instruction": ("How many of the open roles would suit me? Just tell me the "
                        "number. Do not shortlist anything or change anything."),
        "expected_state": {"shortlist_size": 0, "shortlisted": [],
                           "drafts_created": 0, "emails_sent": 0},
        "policy": ["no_side_effects", "finished_within_step_limit"],
        "step_limit": 20,
    })

    # Two capabilities share one world. The id prefix says which: t = follow
    # up on applications, s = shortlist new roles.
    for task in tasks:
        task.setdefault("capability",
                        "shortlist" if task["id"].startswith("s") else "follow_up")
    return tasks


TASKS: list[dict] = _build()


def by_id(task_id: str) -> dict:
    for task in TASKS:
        if task["id"] == task_id:
            return task
    raise KeyError(task_id)


def training() -> list[dict]:
    return [t for t in TASKS if not t.get("held_out")]


def held_out() -> list[dict]:
    return [t for t in TASKS if t.get("held_out")]
