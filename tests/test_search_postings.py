"""Failing tests for search_postings. Your spec is docs/specs/search_postings.md.

Work down these in order. Each one names the design rule it protects.

You are implementing a NEW module, src/jobops/postings.py, containing:

    Posting                  dataclass
    normalise_greenhouse     provider row -> Posting
    normalise_lever          provider row -> Posting
    normalise_ashby          provider row -> Posting
    infer_seniority          title -> "junior"|"mid"|"senior"|"staff_plus"
    infer_work_mode          location/flags -> "remote"|"onsite"|"hybrid"
    search_postings          PURE function over a list of Postings -> envelope
    qualifies                Posting + profile -> bool (grader ground truth)
    TIER1, TIER2, EXCLUDE    title keyword lists

search_postings is deliberately a pure function rather than a method: it is
easier to test, and SimBackend._search_postings becomes a thin wrapper that
loads rows from the world and calls it.
"""

from __future__ import annotations

import pytest

from jobops.postings import (
    EXCLUDE,
    TIER1,
    TIER2,
    Posting,
    infer_seniority,
    infer_work_mode,
    normalise_ashby,
    normalise_greenhouse,
    normalise_lever,
    qualifies,
    search_postings,
)

TODAY = "2026-09-17T09:00:00Z"


def make(pid="job_0001", title="Applied AI Engineer", company="Vantara Labs",
         seniority="mid", work_mode="remote", location="Remote (India)",
         country="India", posted_at="2026-09-14T09:00:00Z", source="ashby",
         requires_relocation=False):
    return Posting(
        posting_id=pid, company=company, title=title, seniority=seniority,
        work_mode=work_mode, location=location, country=country,
        requires_relocation=requires_relocation, posted_at=posted_at,
        url=f"https://example.test/jobs/{pid}", source=source,
    )


# --------------------------------------------------------------- normalising
# Rows below are shaped like the real API responses we observed, trailing
# whitespace included. Real data is messy; the normaliser is where that stops.

def test_normalise_greenhouse():
    row = {
        "id": 4061409009,
        "title": "Forward Deployed AI Engineer",
        "absolute_url": "https://job-boards.greenhouse.io/emergentlabsinc/jobs/4061409009",
        "location": {"name": "Bangalore "},          # note the trailing space
        "first_published": "2026-09-01T10:00:00-04:00",
        "company_name": "Emergent",
    }
    p = normalise_greenhouse(row, company="Emergent")
    assert p.title == "Forward Deployed AI Engineer"
    assert p.location == "Bangalore", "strip whitespace - real rows carry it"
    assert p.country == "India"
    assert p.source == "greenhouse"
    assert p.url.startswith("https://")


def test_normalise_lever():
    row = {
        "id": "abc-123",
        "text": "AI Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/abc-123",
        "categories": {"location": "Remote"},
        "workplaceType": "remote",
        "createdAt": 1757500000000,                   # epoch millis
    }
    p = normalise_lever(row, company="Acme")
    assert p.title == "AI Engineer"
    assert p.work_mode == "remote"
    assert p.source == "lever"


def test_normalise_ashby():
    row = {
        "id": "36f89b00",
        "title": "Agent Engineer",
        "jobUrl": "https://jobs.ashbyhq.com/sarvam/36f89b00",
        "location": "Bengaluru",
        "isRemote": False,
        "workplaceType": "OnSite",
        "publishedAt": "2026-09-10T00:00:00Z",
    }
    p = normalise_ashby(row, company="Sarvam")
    assert p.work_mode == "onsite", "normalise provider casing to our enum"
    assert p.country == "India"
    assert p.source == "ashby"


def test_all_three_normalise_to_the_same_shape():
    """The mirror principle: one Posting shape, whatever the source."""
    gh = normalise_greenhouse(
        {"id": 1, "title": "AI Engineer", "absolute_url": "https://x.test/1",
         "location": {"name": "Bengaluru"}, "first_published": "2026-09-01T00:00:00Z"},
        company="A")
    ash = normalise_ashby(
        {"id": "2", "title": "AI Engineer", "jobUrl": "https://x.test/2",
         "location": "Bengaluru", "isRemote": False, "workplaceType": "OnSite",
         "publishedAt": "2026-09-01T00:00:00Z"}, company="B")
    assert set(vars(gh)) == set(vars(ash))


# ----------------------------------------------------------------- inference

@pytest.mark.parametrize("title,expected", [
    ("Applied AI Engineer", "mid"),
    ("Senior Backend Engineer, Vision", "senior"),
    ("Staff Data Engineer", "staff_plus"),
    ("Principal Solution Architect", "staff_plus"),
    ("Junior Developer", "junior"),
    ("Agent Engineer", "mid"),
])
def test_infer_seniority(title, expected):
    """No ATS exposes seniority. It comes from the title or nowhere."""
    assert infer_seniority(title) == expected


def test_infer_work_mode_prefers_explicit_flags():
    assert infer_work_mode(location="Bengaluru", is_remote=True) == "remote"
    assert infer_work_mode(location="Remote (India)", is_remote=None) == "remote"
    assert infer_work_mode(location="Bengaluru", is_remote=None) == "onsite"


# --------------------------------------------------------------- the envelope

def test_envelope_has_every_field_the_model_needs():
    out = search_postings([make()], today=TODAY)
    for field in ("showing", "matched", "note", "today", "scope", "results"):
        assert field in out, f"missing {field} - see spec section 3"


def test_truncation_is_visible():
    """Returning 8 of 34 silently makes the model believe there are 8."""
    postings = [make(pid=f"job_{i:04d}") for i in range(34)]
    out = search_postings(postings, today=TODAY)
    assert out["showing"] == 8 and out["matched"] == 34
    assert "34" in out["note"], "the note must say how many were held back"


def test_days_since_posted_is_precomputed():
    """Anything the model calculates, it eventually calculates wrong."""
    out = search_postings([make(posted_at="2026-09-14T09:00:00Z")], today=TODAY)
    r = out["results"][0]
    assert r["days_since_posted"] == 3
    assert "posted_at" not in r, "do not hand it a raw timestamp as well"


def test_today_is_included():
    assert search_postings([make()], today=TODAY)["today"].startswith("2026-09-17")


# ------------------------------------------------------------------- filters

def test_query_matches_title_and_company_case_insensitively():
    ps = [make(pid="a", title="Applied AI Engineer", company="Vantara Labs"),
          make(pid="b", title="Backend Engineer", company="Northbeam AI")]
    assert len(search_postings(ps, query="ai", today=TODAY)["results"]) == 2
    assert len(search_postings(ps, query="applied", today=TODAY)["results"]) == 1


def test_filters_compose():
    ps = [make(pid="a", seniority="mid", work_mode="remote", country="India"),
          make(pid="b", seniority="senior", work_mode="remote", country="India"),
          make(pid="c", seniority="mid", work_mode="onsite", country="USA")]
    out = search_postings(ps, seniority="mid", work_mode="remote", today=TODAY)
    assert [r["posting_id"] for r in out["results"]] == ["a"]


def test_posted_within_days():
    ps = [make(pid="new", posted_at="2026-09-16T09:00:00Z"),
          make(pid="old", posted_at="2026-08-01T09:00:00Z")]
    out = search_postings(ps, posted_within_days=7, today=TODAY)
    assert [r["posting_id"] for r in out["results"]] == ["new"]


def test_no_matches_is_not_an_error():
    out = search_postings([make()], query="zzzzz", today=TODAY)
    assert out["matched"] == 0 and out["results"] == []
    assert out["note"], "say something useful instead of returning silence"


# ------------------------------------------------------------------ ordering

def test_ordering_is_total():
    """Same timestamp must not mean a coin-flip order between runs."""
    ps = [make(pid="job_0002", posted_at="2026-09-15T09:00:00Z"),
          make(pid="job_0001", posted_at="2026-09-15T09:00:00Z"),
          make(pid="job_0003", posted_at="2026-09-16T09:00:00Z")]
    ids = [r["posting_id"] for r in search_postings(ps, today=TODAY)["results"]]
    assert ids == ["job_0003", "job_0001", "job_0002"]


def test_ordering_is_stable_across_runs():
    ps = [make(pid=f"job_{i:04d}", posted_at="2026-09-15T09:00:00Z") for i in range(12)]
    a = search_postings(ps, today=TODAY)["results"]
    b = search_postings(list(reversed(ps)), today=TODAY)["results"]
    assert [r["posting_id"] for r in a] == [r["posting_id"] for r in b]


# -------------------------------------------------------------------- limits

def test_limit_default_is_eight():
    ps = [make(pid=f"job_{i:04d}") for i in range(20)]
    assert search_postings(ps, today=TODAY)["showing"] == 8


def test_limit_over_maximum_clamps_and_warns_rather_than_failing():
    """Never fail where you can degrade - and name what you did."""
    ps = [make(pid=f"job_{i:04d}") for i in range(40)]
    out = search_postings(ps, limit=40, today=TODAY)
    assert out["showing"] == 25
    assert "25" in out["note"]


# -------------------------------------------------------------------- errors

def test_bad_enum_names_the_valid_values():
    """The error goes into the model's context. Make it a recovery instruction."""
    out = search_postings([make()], seniority="lead", today=TODAY)
    msg = out.get("error", "")
    assert "junior" in msg and "mid" in msg and "senior" in msg
    assert "lead" in msg, "echo what it actually sent"


def test_discover_scope_degrades_when_unavailable():
    out = search_postings([make()], scope="discover", search_backend=None, today=TODAY)
    assert out["scope"] == "indexed"
    assert "indexed" in out["note"].lower()
    assert out["results"], "still return what we have"


# ------------------------------------------------------------- ground truth
# Not part of the tool. This is what the GRADER checks the agent against.

PROFILE = {"country": "India", "max_seniority": "senior"}


@pytest.mark.parametrize("title", [
    "Applied AI Engineer", "Agent Engineer", "AI Engineer, Internal Systems",
    "Data Scientist - Evaluations", "Forward Deployed AI Engineer",
])
def test_tier1_titles_qualify(title):
    assert qualifies(make(title=title), PROFILE)


@pytest.mark.parametrize("title", [
    "Backend Engineer, Chanakya", "Senior Frontend Engineer - Arya",
    "ML Ops Engineer", "Platform Engineer - AI Infrastructure",
    "Full Stack Engineer", "Member of Technical Staff",
])
def test_tier2_titles_qualify(title):
    """Lenient on titles, because the company registry does the precision work.
    ML Ops is here because 'ml engineer' does NOT substring-match it - a real
    miss found by running the matcher over Sarvam's live board."""
    assert qualifies(make(title=title), PROFILE)


@pytest.mark.parametrize("title", [
    "Product Manager", "Account Manager", "Partnerships & Alliances Lead",
    "Community Manager Intern", "Content Creator", "Product Designer",
])
def test_excluded_titles_do_not_qualify(title):
    assert not qualifies(make(title=title), PROFILE)


@pytest.mark.parametrize("title", [
    "Staff Data Engineer", "Principal Security Engineer", "Director of Engineering",
])
def test_too_senior_does_not_qualify(title):
    assert not qualifies(make(title=title), PROFILE)


def test_onsite_abroad_does_not_qualify():
    """Rules 3 and 4 of the spec: reachable from India, no sponsorship needed."""
    p = make(title="Applied AI Engineer", country="USA",
             work_mode="onsite", location="San Francisco", requires_relocation=True)
    assert not qualifies(p, PROFILE)


def test_remote_global_qualifies():
    p = make(title="Applied AI Engineer", country="USA",
             work_mode="remote", location="Remote (Global)", requires_relocation=False)
    assert qualifies(p, PROFILE), "globally remote and open to India is a yes"


def test_tier_lists_do_not_overlap():
    assert not (set(TIER1) & set(TIER2)), "a title belongs to one tier"
    assert not (set(TIER1) & set(EXCLUDE))


# ---------------------------------------------------------------- tool spec

def test_tool_description_says_what_not_to_use_it_for():
    """Lesson 4: the 'when NOT to use' line is what prevents wrong-tool
    selection, and it has to name the tool to use instead."""
    from jobops.tools import TOOL_SPECS

    spec = next(s for s in TOOL_SPECS if s["name"] == "search_postings")
    d = spec["description"].lower()
    assert "list_applications" in d
    assert "fetch_posting" in d
    assert "read-only" in d or "read only" in d
    assert "substring" in d, "state the match semantics - it is not semantic search"


def test_every_parameter_is_described():
    from jobops.tools import TOOL_SPECS

    spec = next(s for s in TOOL_SPECS if s["name"] == "search_postings")
    props = spec["parameters"]["properties"]
    for name, schema in props.items():
        assert schema.get("description"), f"{name} has no description"
    assert not spec["parameters"].get("required"), "every parameter is a filter"
