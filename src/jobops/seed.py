"""Deterministic world generation.

Everything here is driven by one `random.Random(seed)`. No global random, no
clock, no network. Seed 42 builds the identical world on every machine, forever.

Applications are generated in four deliberate categories so that tasks have a
knowable right answer AND built-in distractors:

  stale             applied long ago, we spoke last, they never replied   -> needs follow-up
  replied           applied long ago, but THEY replied                    -> distractor
  followed_recently applied long ago, we already nudged them recently     -> distractor
  fresh             applied a few days ago                                -> distractor

Only the first category is genuinely stale. An agent that follows up on
"anything old" will fail; one that applies the rule will pass.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .clock import Clock

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

TITLES = [
    ("Applied AI Engineer", "mid"),
    ("AI Engineer, Agents", "mid"),
    ("Forward Deployed Engineer", "mid"),
    ("Senior Frontend Engineer", "senior"),
    ("Member of Technical Staff", "mid"),
    ("Agent Infrastructure Engineer", "mid"),
    ("AI Engineer, Internal Systems", "mid"),
    ("Full Stack AI Engineer", "mid"),
    ("Evaluation Engineer", "mid"),
    ("Platform Engineer, LLM", "senior"),
]

LOCATIONS = ["Bengaluru", "Remote (India)", "Remote (Global)", "Mumbai", "Hyderabad", "Pune"]

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


@dataclass
class WorldSetup:
    """The knobs a task turns to shape the world it needs."""

    stale: int = 3
    replied: int = 2
    followed_recently: int = 2
    fresh: int = 3
    extra_open_postings: int = 20
    staleness_days: int = 7

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


def generate(seed: int, setup: WorldSetup, clock: Clock) -> GeneratedWorld:
    rng = random.Random(seed)
    out = GeneratedWorld()

    n_applied_companies = setup.total_applications
    n_companies = min(len(COMPANY_NAMES), n_applied_companies + 10)

    chosen = rng.sample(COMPANY_NAMES, n_companies)
    for i, (name, domain, industry) in enumerate(chosen, start=1):
        out.companies.append((f"co_{i:03d}", name, domain, industry))

    posting_no = 0

    def add_posting(company_id: str, days_old: float) -> str:
        nonlocal posting_no
        posting_no += 1
        pid = f"job_{posting_no:04d}"
        title, seniority = rng.choice(TITLES)
        company = next(c for c in out.companies if c[0] == company_id)
        out.postings.append((
            pid, company_id, title, seniority,
            rng.choice(LOCATIONS), int(rng.random() < 0.45),
            clock.ago(days_old),
            f"https://{company[2]}/careers/{pid}",
            "open",
        ))
        return pid

    # One posting per company we have applied to, so "don't contact the same
    # company twice" is a rule an agent can actually violate.
    applied_companies = [c[0] for c in out.companies[:n_applied_companies]]

    app_no = 0
    msg_no = 0

    def add_application(company_id: str, category: str) -> None:
        nonlocal app_no, msg_no
        app_no += 1
        aid = f"app_{app_no:03d}"

        if category == "stale":
            applied_days = rng.uniform(setup.staleness_days + 5, 30)
            applied_at = clock.ago(applied_days)
            out.applications.append((aid, add_posting(company_id, applied_days + 3),
                                     "applied", applied_at, applied_at, None, 0, None))

        elif category == "replied":
            applied_days = rng.uniform(10, 25)
            applied_at = clock.ago(applied_days)
            inbound_at = clock.ago(rng.uniform(1, 5))
            pid = add_posting(company_id, applied_days + 3)
            out.applications.append((aid, pid, "applied", applied_at, applied_at, inbound_at, 0, None))
            msg_no += 1
            posting = next(p for p in out.postings if p[0] == pid)
            company = next(c for c in out.companies if c[0] == company_id)
            out.messages.append((
                f"msg_{msg_no:04d}", aid, "inbound",
                rng.choice(INBOUND_SUBJECTS).format(title=posting[2], company=company[1]),
                rng.choice(INBOUND_BODIES), inbound_at, "received", None, None,
            ))

        elif category == "followed_recently":
            applied_days = rng.uniform(20, 40)
            applied_at = clock.ago(applied_days)
            nudged_at = clock.ago(rng.uniform(1, setup.staleness_days - 3))
            out.applications.append((aid, add_posting(company_id, applied_days + 3),
                                     "applied", applied_at, nudged_at, None, 1, None))

        elif category == "fresh":
            applied_days = rng.uniform(0.5, 4)
            applied_at = clock.ago(applied_days)
            out.applications.append((aid, add_posting(company_id, applied_days + 2),
                                     "applied", applied_at, applied_at, None, 0, None))

        else:  # pragma: no cover - guarded by callers
            raise ValueError(f"unknown category {category!r}")

    plan = (["stale"] * setup.stale + ["replied"] * setup.replied
            + ["followed_recently"] * setup.followed_recently + ["fresh"] * setup.fresh)
    # Shuffle so category is not correlated with application id. Without this,
    # app_001..app_00N are always the stale ones and an agent can pattern-match
    # the ids instead of applying the rule - a reward hack we handed it for free.
    rng.shuffle(plan)
    for company_id, category in zip(applied_companies, plan):
        add_application(company_id, category)

    # Open postings we have NOT applied to, so search returns more than our own history.
    untouched = [c[0] for c in out.companies[n_applied_companies:]]
    for i in range(setup.extra_open_postings):
        if not untouched:
            break
        add_posting(untouched[i % len(untouched)], rng.uniform(1, 40))

    return out
