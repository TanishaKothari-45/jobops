"""Postings: one shape, three providers, and the rule that decides what counts.

Three jobs live here:

  1. NORMALISING - Greenhouse, Lever and Ashby each describe a job differently.
     The adapters turn all three into one `Posting`. This is where messy real
     data stops being messy; one live Greenhouse row came back with the location
     "Bangalore " (trailing space), which is exactly the sort of thing that
     should never reach the agent.

  2. SEARCHING - `search_postings` is a PURE function over a list of Postings.
     Pure because it is easier to test, and because the tool handler then
     becomes a thin wrapper that loads rows and calls it.

  3. QUALIFYING - `qualifies` is the grader's ground truth, not part of the
     tool. It lives here because it is defined over the same fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .clock import days_between, fmt

# --------------------------------------------------------------------- shape


@dataclass
class Posting:
    posting_id: str
    company: str
    title: str
    seniority: str          # junior | mid | senior | staff_plus
    work_mode: str          # remote | onsite | hybrid
    location: str
    country: str | None
    requires_relocation: bool
    posted_at: str          # ISO-8601 UTC
    url: str
    source: str             # greenhouse | lever | ashby | seed


SENIORITY_VALUES = ("junior", "mid", "senior", "staff_plus")
WORK_MODE_VALUES = ("remote", "onsite", "hybrid")
SCOPE_VALUES = ("indexed", "discover")

DEFAULT_LIMIT = 8
MAX_LIMIT = 25


# ----------------------------------------------------------------- inference

# No ATS exposes seniority. It comes from the title or it comes from nowhere.
_STAFF_PLUS = ("staff", "principal", "director", "head of", "vp ", "chief",
               "distinguished")
_SENIOR = ("senior", "sr.", "sr ", "lead ")
_JUNIOR = ("junior", "jr.", "jr ", "intern", "graduate", "new grad", "trainee")


# "Member of Technical Staff" contains the word "staff" but is a MID-level IC
# title at AI companies (OpenAI, Anthropic, Sarvam all use it). A naive keyword
# matcher classifies it staff_plus and filters out exactly the roles we want.
_NOT_SENIORITY_SIGNALS = ("member of technical staff", "technical staff", "mts")


def infer_seniority(title: str) -> str:
    t = f" {title.lower().strip()} "
    for phrase in _NOT_SENIORITY_SIGNALS:
        t = t.replace(phrase, " ")
    if any(k in t for k in _STAFF_PLUS):
        return "staff_plus"
    if any(k in t for k in _JUNIOR):
        return "junior"
    if any(k in t for k in _SENIOR):
        return "senior"
    return "mid"


def infer_work_mode(location: str | None = None, is_remote: bool | None = None,
                    workplace_type: str | None = None) -> str:
    """Explicit provider flags win; location text is the fallback.

    Greenhouse exposes no work-mode field at all, so for those rows the only
    signal is whatever the location string says.
    """
    if is_remote is True:
        return "remote"
    if workplace_type:
        w = workplace_type.strip().lower().replace("-", "").replace(" ", "")
        if w in ("remote", "fullyremote"):
            return "remote"
        if w == "hybrid":
            return "hybrid"
        if w in ("onsite", "inoffice", "office"):
            return "onsite"
    loc = (location or "").lower()
    if "remote" in loc or "anywhere" in loc:
        return "remote"
    if "hybrid" in loc:
        return "hybrid"
    return "onsite"


_COUNTRY_HINTS = (
    ("India", ("india", "bangalore", "bengaluru", "mumbai", "delhi", "gurgaon",
               "gurugram", "noida", "hyderabad", "pune", "chennai", "kolkata")),
    ("USA", ("united states", "usa", "san francisco", "new york", "seattle",
             "austin", "boston", "palo alto", "mountain view")),
    ("UK", ("united kingdom", "london", "manchester", "edinburgh")),
    ("Singapore", ("singapore",)),
    ("Germany", ("germany", "berlin", "munich")),
    ("Canada", ("canada", "toronto", "vancouver")),
)


def infer_country(location: str | None) -> str | None:
    """Location strings are free text, so this is a heuristic and named as one.

    Returns None rather than guessing when nothing matches - a missing country
    the agent can see beats a wrong one it cannot.
    """
    if not location:
        return None
    loc = location.lower()
    for country, hints in _COUNTRY_HINTS:
        if any(h in loc for h in hints):
            return country
    return None


def infer_requires_relocation(country: str | None, work_mode: str,
                              home_country: str = "India") -> bool:
    """Sponsorship is not a field ANY provider exposes, so it is inferred.

    Remote work needs no relocation. Otherwise an on-site role in another
    country does. An unknown country is treated as not requiring relocation, so
    the role still surfaces and the agent judges it - a false negative the agent
    can catch beats a true positive it never sees.
    """
    if work_mode == "remote":
        return False
    if country is None:
        return False
    return country != home_country


# ---------------------------------------------------------------- normalisers


def _utc(value) -> str:
    """Providers disagree about time. Everything becomes one ISO-8601 UTC string."""
    if value is None:
        return fmt(datetime.now(timezone.utc))
    if isinstance(value, (int, float)):                   # Lever: epoch millis
        return fmt(datetime.fromtimestamp(value / 1000, tz=timezone.utc))
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)                 # handles -04:00 offsets
    except ValueError:
        return fmt(datetime.now(timezone.utc))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return fmt(dt)


def _build(posting_id, company, title, location, url, posted_at, source,
           is_remote=None, workplace_type=None) -> Posting:
    location = (location or "").strip()
    title = (title or "").strip()
    work_mode = infer_work_mode(location, is_remote, workplace_type)
    country = infer_country(location)
    return Posting(
        posting_id=str(posting_id),
        company=company,
        title=title,
        seniority=infer_seniority(title),
        work_mode=work_mode,
        location=location,
        country=country,
        requires_relocation=infer_requires_relocation(country, work_mode),
        posted_at=_utc(posted_at),
        url=url or "",
        source=source,
    )


def normalise_greenhouse(row: dict, company: str) -> Posting:
    """Greenhouse's list endpoint carries no description and no work-mode field."""
    return _build(
        posting_id=row.get("id"),
        company=company or row.get("company_name", ""),
        title=row.get("title"),
        location=(row.get("location") or {}).get("name"),
        url=row.get("absolute_url"),
        posted_at=row.get("first_published") or row.get("updated_at"),
        source="greenhouse",
    )


def normalise_lever(row: dict, company: str) -> Posting:
    return _build(
        posting_id=row.get("id"),
        company=company,
        title=row.get("text"),
        location=(row.get("categories") or {}).get("location"),
        url=row.get("hostedUrl") or row.get("applyUrl"),
        posted_at=row.get("createdAt"),
        source="lever",
        workplace_type=row.get("workplaceType"),
    )


def normalise_ashby(row: dict, company: str) -> Posting:
    return _build(
        posting_id=row.get("id"),
        company=company,
        title=row.get("title"),
        location=row.get("location"),
        url=row.get("jobUrl") or row.get("applyUrl"),
        posted_at=row.get("publishedAt"),
        source="ashby",
        is_remote=row.get("isRemote"),
        workplace_type=row.get("workplaceType"),
    )


NORMALISERS = {
    "greenhouse": normalise_greenhouse,
    "lever": normalise_lever,
    "ashby": normalise_ashby,
}


# -------------------------------------------------------------------- search


class _AscId:
    """Sorts ids ascending inside an otherwise descending sort."""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value

    def __lt__(self, other: "_AscId") -> bool:
        return self.value > other.value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _AscId) and self.value == other.value


def _err(message: str, today: str) -> dict:
    return {"error": message, "showing": 0, "matched": 0, "results": [],
            "note": message, "today": today, "scope": "indexed"}


def _as_result(p: Posting, today: str) -> dict:
    """What the model sees. Note what is NOT here: posted_at.

    Handing over a raw timestamp invites the model to do date arithmetic, and
    anything it calculates it eventually calculates wrong.
    """
    return {
        "posting_id": p.posting_id,
        "company": p.company,
        "title": p.title,
        "seniority": p.seniority,
        "work_mode": p.work_mode,
        "location": p.location,
        "country": p.country,
        "requires_relocation": p.requires_relocation,
        "days_since_posted": int(days_between(p.posted_at, today)),
        "url": p.url,
        "source": p.source,
    }


def search_postings(postings: list[Posting], *, query: str | None = None,
                    seniority: str | None = None, work_mode: str | None = None,
                    country: str | None = None,
                    posted_within_days: int | None = None,
                    scope: str = "indexed", limit: int = DEFAULT_LIMIT,
                    search_backend=None, today: str | None = None) -> dict:
    """Filter, order, bound, wrap. Pure - no world, no clock, no network."""
    today = today or fmt(datetime.now(timezone.utc))
    notes: list[str] = []

    # Enum errors name the valid values and echo what was sent, because this
    # text lands in the model's context and becomes a recovery instruction.
    for name, value, allowed in (("seniority", seniority, SENIORITY_VALUES),
                                 ("work_mode", work_mode, WORK_MODE_VALUES),
                                 ("scope", scope, SCOPE_VALUES)):
        if value is not None and value not in allowed:
            return _err(f"{name} must be one of {', '.join(allowed)}; got {value!r}.", today)

    effective_scope = scope
    if scope == "discover" and search_backend is None:
        effective_scope = "indexed"
        notes.append("Discovery is unavailable (no search backend configured). "
                     "Showing indexed results only.")

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return _err(f"limit must be an integer between 1 and {MAX_LIMIT}; got {limit!r}.", today)
    if limit > MAX_LIMIT:
        notes.append(f"limit must be between 1 and {MAX_LIMIT}; got {limit}. "
                     f"Using {MAX_LIMIT}.")
        limit = MAX_LIMIT
    elif limit < 1:
        notes.append(f"limit must be at least 1; got {limit}. Using {DEFAULT_LIMIT}.")
        limit = DEFAULT_LIMIT

    rows = list(postings)
    if query:
        q = query.lower()
        rows = [p for p in rows if q in p.title.lower() or q in p.company.lower()]
    if seniority:
        rows = [p for p in rows if p.seniority == seniority]
    if work_mode:
        rows = [p for p in rows if p.work_mode == work_mode]
    if country:
        rows = [p for p in rows if (p.country or "").lower() == country.lower()]
    if posted_within_days is not None:
        rows = [p for p in rows
                if days_between(p.posted_at, today) <= posted_within_days]

    # Total ordering. The id tiebreak is not decoration: without it two postings
    # sharing a timestamp can swap between runs, and an unrepeatable run cannot
    # be graded.
    rows.sort(key=lambda p: (p.posted_at, _AscId(p.posting_id)), reverse=True)

    matched = len(rows)
    page = rows[:limit]

    if matched == 0:
        notes.append("No postings matched. Try a broader query, or drop a filter.")
    elif matched > len(page):
        notes.append(f"Showing {len(page)} of {matched}. "
                     "Narrow with query, seniority or country.")

    return {
        "showing": len(page),
        "matched": matched,
        "note": " ".join(notes),
        "today": today,
        "scope": effective_scope,
        "results": [_as_result(p, today) for p in page],
    }


# -------------------------------------------------------------- ground truth
# Not part of the tool. This is what the GRADER checks the agent against.
#
# Deliberately LENIENT on titles, because the company registry already does the
# precision work: if we only track AI-native companies worth joining, then
# "Backend Engineer" at one of them is genuinely a role worth considering.

TIER1 = [
    "applied ai", "ai engineer", "agent engineer", "forward deployed",
    "evaluation", "evals", "llm", "member of technical staff", "mts",
    "research engineer", "agentic",
]

TIER2 = [
    "software engineer", "backend engineer", "frontend engineer",
    "front end engineer", "full stack", "fullstack", "product engineer",
    "platform engineer", "ml engineer", "mlops", "ml ops", "machine learning",
    "data scientist", "solutions engineer", "solution engineer",
    "solutions architect", "solution architect", "deployment engineer",
    "implementation engineer", "genai", "generative ai", "researcher",
    "infrastructure engineer", "data engineer", "performance engineer",
    "systems engineer",
]

# Checked FIRST. A loose title matcher would otherwise pull these in from a real
# board - every one of these appeared on Sarvam's live listing.
EXCLUDE = [
    "product manager", "engagement manager", "account manager", "partnership",
    "marketing", "sales", "recruit", "finance", "it lead", "community",
    "content creator", "designer", "specialist", "gtm", "operations manager",
    "cfo", "business development", "people ops", "advocate", "editor",
    "analyst",
]


def title_tier(title: str) -> str | None:
    """'tier1' | 'tier2' | None. Exclusions win over both."""
    t = title.lower()
    if any(k in t for k in EXCLUDE):
        return None
    if any(k in t for k in TIER1):
        return "tier1"
    if any(k in t for k in TIER2):
        return "tier2"
    return None


_SENIORITY_RANK = {"junior": 0, "mid": 1, "senior": 2, "staff_plus": 3}


def qualifies_row(row: dict, profile: dict) -> bool:
    """`qualifies` over a search RESULT dict - what an agent actually sees.

    The grader judges `Posting` objects read from the world; an agent only ever
    holds result rows. Both must reach the same verdict, so both go through the
    same rule rather than two implementations that can drift apart.
    """
    return qualifies(Posting(
        posting_id=row.get("posting_id", ""), company=row.get("company", ""),
        title=row.get("title", ""), seniority=row.get("seniority", "mid"),
        work_mode=row.get("work_mode", "onsite"), location=row.get("location", ""),
        country=row.get("country"),
        requires_relocation=bool(row.get("requires_relocation")),
        posted_at="", url=row.get("url", ""), source=row.get("source", ""),
    ), profile)


def qualifies(posting: Posting, profile: dict) -> bool:
    """All four rules must hold. See docs/specs/search_postings.md section 7.

    Seniority is re-inferred from the title rather than trusted from the field,
    because the rule is defined on what the posting SAYS it is.
    """
    if title_tier(posting.title) is None:
        return False

    max_rank = _SENIORITY_RANK.get(profile.get("max_seniority", "senior"), 2)
    if _SENIORITY_RANK.get(infer_seniority(posting.title), 1) > max_rank:
        return False

    home = profile.get("country", "India")
    reachable = (posting.country == home) or (posting.work_mode == "remote")
    if not reachable:
        return False

    return not posting.requires_relocation
