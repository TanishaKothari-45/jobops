"""Deterministic world generation.

Everything here is driven by one `random.Random(seed)`. No global random, no
clock, no network. Seed 42 builds the identical world on every machine, forever.

Applications come in four deliberate categories so follow-up tasks have a
knowable right answer AND built-in distractors:

  stale             applied long ago, we spoke last, they never replied   -> needs follow-up
  replied           applied long ago, but THEY replied                    -> distractor
  followed_recently applied long ago, we already nudged them recently     -> distractor
  fresh             applied a few days ago                                -> distractor

Postings carry their own distractors for the shortlisting agent: titles that do
not qualify (Product Manager), roles too senior (Principal Engineer), and
on-site roles abroad that would need relocation. An agent that shortlists on
"sounds like engineering" fails; one that applies the rule passes.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

from .clock import Clock
from .postings import infer_requires_relocation, infer_seniority

COMPANY_NAMES = [
    ("Vantara Labs", "vantaralabs.com", "AI infrastructure"),
    ("Northbeam AI", "northbeam.ai", "developer tools"),
    ("Kestrel Systems", "kestrelsys.io", "AI infrastructure"),
    ("Lumen Retrieval", "lumenretrieval.com", "search"),
    ("Praxis Compute", "praxiscompute.com", "cloud"),
    ("Ferrous Analytics", "ferrous.dev", "data"),
    ("Olive Interfaces", "oliveinterfaces.com", "consumer AI"),
    ("Tern Robotics", "ternrobotics.ai", "robotics"),
    ("Harbour Intelligence", "harbourint.com", "fintech"),
    ("Solace Health AI", "solacehealth.ai", "healthcare"),
    ("Gradient Works", "gradientworks.io", "MLOps"),
    ("Anvil Semantics", "anvilsemantics.com", "NLP"),
    ("Rill Networks", "rillnetworks.com", "networking"),
    ("Cobalt Agents", "cobaltagents.ai", "agent platforms"),
    ("Meridian Voice", "meridianvoice.ai", "speech"),
    ("Thicket Data", "thicketdata.com", "data"),
    ("Lantern Security", "lanternsec.io", "security"),
    ("Pale Blue Compute", "palebluecompute.com", "cloud"),
    ("Sable Forecasting", "sableforecasting.com", "fintech"),
    ("Quarry Systems", "quarrysystems.dev", "developer tools"),
    ("Ionic Retrieval", "ionicretrieval.ai", "search"),
    ("Deepfield Studio", "deepfield.studio", "consumer AI"),
    ("Auric Platform", "auricplatform.com", "agent platforms"),
    ("Crest Modelworks", "crestmodelworks.ai", "ML research"),
]

# Mixed on purpose. Roughly a third of these must NOT qualify, or the
# shortlisting task is trivial and measures nothing.
TITLES = [
    "Applied AI Engineer",
    "AI Engineer, Agents",
    "Agent Engineer",
    "Forward Deployed Engineer",
    "Member of Technical Staff",
    "Evaluation Engineer",
    "Research Engineer, Retrieval",
    "Backend Engineer",
    "Senior Frontend Engineer",
    "Full Stack Engineer",
    "Platform Engineer, Inference",
    "ML Ops Engineer",
    "Data Scientist",
    "Product Manager",            # excluded by title
    "Account Manager",            # excluded by title
    "Product Designer",           # excluded by title
    "Marketing Lead",             # excluded by title
    "Staff Engineer, Training",   # too senior
    "Principal Engineer",         # too senior
    "Director of Engineering",    # too senior
]

# (location, country, work_mode)
PLACES_INDIA = [
    ("Bengaluru", "India", "onsite"),
    ("Remote (India)", "India", "remote"),
    ("Mumbai", "India", "onsite"),
    ("Hyderabad", "India", "onsite"),
    ("Pune", "India", "hybrid"),
]
PLACES_ALL = PLACES_INDIA + [
    ("Remote (Global)", None, "remote"),
    ("San Francisco", "USA", "onsite"),      # would need relocation
    ("New York", "USA", "onsite"),           # would need relocation
    ("London", "UK", "onsite"),              # would need relocation
]

ATS_PROVIDERS = ("greenhouse", "lever", "ashby")
FUNDING_STAGES = ("seed", "series_a", "series_b", "series_c")
STAGE_RANGE = {
    "seed": (2_000_000, 8_000_000),
    "series_a": (10_000_000, 30_000_000),
    "series_b": (35_000_000, 90_000_000),
    "series_c": (100_000_000, 250_000_000),
}

STACKS = [
    ["Python", "FastAPI", "Postgres"],
    ["Python", "LangGraph", "Redis"],
    ["TypeScript", "React", "Next.js"],
    ["Python", "PyTorch", "Ray"],
    ["Go", "Kubernetes", "gRPC"],
]

INBOUND_SUBJECTS = [
    "Re: Application for {title}",
    "Thanks for applying to {company}",
    "Next steps - {title}",
]
INBOUND_BODIES = [
    "Thanks for your interest. We're reviewing applications this week and will be in touch.",
    "Appreciate you applying. Could you share your availability for a short call?",
    "We've received your application and passed it to the hiring manager.",
]

PROFILE = (
    1,
    "Tanisha Kothari",
    "Applied AI Engineer - production LLM agents and evaluation",
    3,
    "India",
    "senior",
    1,   # open_to_remote
    1,   # needs_sponsorship: cannot take a role that requires a work visa
    json.dumps(["Python", "FastAPI", "LangGraph", "React", "TypeScript",
                "RAG", "Pinecone", "MCP", "evaluation", "Redis", "MongoDB"]),
    # These must cover every TIER1 concept in postings.py. The grader treats a
    # tier-1 role as one the agent should have found, so a tier-1 keyword with
    # no matching target title here is a role we punish it for missing while
    # never telling it to look. test_target_titles_cover_tier1 guards the drift.
    json.dumps(["Applied AI Engineer", "AI Engineer", "Agent Engineer",
                "Forward Deployed Engineer", "Member of Technical Staff",
                "Research Engineer", "Evaluation Engineer", "LLM Engineer",
                "Agentic Systems Engineer"]),
)


@dataclass
class WorldSetup:
    """The knobs a task turns to shape the world it needs."""

    stale: int = 3
    replied: int = 2
    followed_recently: int = 2
    fresh: int = 3
    extra_open_postings: int = 30
    staleness_days: int = 7

    # Restrict the title pool for the non-applied postings. A world built only
    # from excluded or too-senior titles is how we test ABSTENTION - plenty to
    # look at, nothing worth picking.
    only_titles: tuple[str, ...] | None = None
    # Tools that fail on every call, to test error recovery on purpose.
    broken_tools: tuple[str, ...] = ()
    # Serve search results in reverse order. Paired with an identical task in
    # natural order this is a permutation test: an agent reading position
    # rather than content produces a different shortlist.
    reverse_search_order: bool = False

    @property
    def total_applications(self) -> int:
        return self.stale + self.replied + self.followed_recently + self.fresh

    @classmethod
    def from_dict(cls, d: dict | None) -> "WorldSetup":
        return cls(**(d or {}))


@dataclass
class GeneratedWorld:
    companies: list[tuple] = field(default_factory=list)
    postings: list[tuple] = field(default_factory=list)
    applications: list[tuple] = field(default_factory=list)
    messages: list[tuple] = field(default_factory=list)
    profile: tuple = PROFILE


def _description(rng: random.Random, title: str, company: str) -> str:
    stack = rng.choice(STACKS)
    return (f"{company} is hiring a {title}. You will work across "
            f"{', '.join(stack)}. We care about shipping to real users and "
            f"measuring what we ship.")


def generate(seed: int, setup: WorldSetup, clock: Clock) -> GeneratedWorld:
    rng = random.Random(seed)
    out = GeneratedWorld()

    n_applied_companies = setup.total_applications
    n_companies = min(len(COMPANY_NAMES), n_applied_companies + 12)

    for i, (name, domain, industry) in enumerate(
            rng.sample(COMPANY_NAMES, n_companies), start=1):
        stage = rng.choice(FUNDING_STAGES)
        low, high = STAGE_RANGE[stage]
        out.companies.append((
            f"co_{i:03d}", name, domain, industry,
            rng.choice([25, 40, 80, 150, 300, 600]),
            stage,
            rng.randrange(low, high, 500_000),
            clock.ago(rng.uniform(30, 720)),
            rng.choice(ATS_PROVIDERS),
            domain.split(".")[0],
            1,
        ))

    posting_no = 0

    def add_posting(company_id: str, days_old: float, *, india_only: bool,
                    pool: tuple[str, ...] | list[str] = TITLES) -> str:
        nonlocal posting_no
        posting_no += 1
        pid = f"job_{posting_no:04d}"
        title = rng.choice(list(pool))
        company = next(c for c in out.companies if c[0] == company_id)
        location, country, work_mode = rng.choice(
            PLACES_INDIA if india_only else PLACES_ALL)
        out.postings.append((
            pid, company_id, title, infer_seniority(title), location, country,
            work_mode, int(infer_requires_relocation(country, work_mode)),
            int(work_mode == "remote"), clock.ago(days_old),
            f"https://{company[2]}/careers/{pid}", "seed",
            _description(rng, title, company[1]), "open",
        ))
        return pid

    applied_companies = [c[0] for c in out.companies[:n_applied_companies]]
    app_no = 0
    msg_no = 0

    def add_application(company_id: str, category: str) -> None:
        nonlocal app_no, msg_no
        app_no += 1
        aid = f"app_{app_no:03d}"

        # Applications always point at India-based roles, so the follow-up
        # tasks are unaffected by the shortlisting distractors.
        def mk(days: float) -> str:
            return add_posting(company_id, days, india_only=True)

        if category == "stale":
            days = rng.uniform(setup.staleness_days + 5, 30)
            at = clock.ago(days)
            out.applications.append((aid, mk(days + 3), "applied", at, at, None, 0, None))

        elif category == "replied":
            days = rng.uniform(10, 25)
            at = clock.ago(days)
            inbound_at = clock.ago(rng.uniform(1, 5))
            pid = mk(days + 3)
            out.applications.append((aid, pid, "applied", at, at, inbound_at, 0, None))
            msg_no += 1
            posting = next(p for p in out.postings if p[0] == pid)
            company = next(c for c in out.companies if c[0] == company_id)
            out.messages.append((
                f"msg_{msg_no:04d}", aid, "inbound",
                rng.choice(INBOUND_SUBJECTS).format(title=posting[2], company=company[1]),
                rng.choice(INBOUND_BODIES), inbound_at, "received", None, None,
            ))

        elif category == "followed_recently":
            days = rng.uniform(20, 40)
            at = clock.ago(days)
            nudged = clock.ago(rng.uniform(1, setup.staleness_days - 3))
            out.applications.append((aid, mk(days + 3), "applied", at, nudged, None, 1, None))

        elif category == "fresh":
            days = rng.uniform(0.5, 4)
            at = clock.ago(days)
            out.applications.append((aid, mk(days + 2), "applied", at, at, None, 0, None))

        else:  # pragma: no cover
            raise ValueError(f"unknown category {category!r}")

    plan = (["stale"] * setup.stale + ["replied"] * setup.replied
            + ["followed_recently"] * setup.followed_recently + ["fresh"] * setup.fresh)
    # Shuffle so category is not correlated with application id. Without this,
    # app_001..app_00N are always the stale ones and an agent can pattern-match
    # the ids instead of applying the rule - a reward hack we handed it for free.
    rng.shuffle(plan)
    for company_id, category in zip(applied_companies, plan):
        add_application(company_id, category)

    # Open postings we have NOT applied to. This is the shortlister's search
    # space, so it carries the full spread of locations and titles.
    untouched = [c[0] for c in out.companies[n_applied_companies:]] or applied_companies
    pool = setup.only_titles or TITLES
    for i in range(setup.extra_open_postings):
        add_posting(untouched[i % len(untouched)], rng.uniform(1, 40),
                    india_only=False, pool=pool)

    return out
