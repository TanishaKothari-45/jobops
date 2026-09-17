# Spec — `search_postings`

Your contract. You implement it; the tests in `tests/test_search_postings.py`
check that you did. Read this once, then work test by test.

Design decisions already made (yours):
- **Dumb retriever.** This tool does not judge fit. `get_profile` exists so the
  agent judges fit itself, where we can see it.
- **Role-first.** The agent asks for a role. Company-wise fetching is plumbing
  it never sees.
- **Split from `fetch_posting`.** Greenhouse's list endpoint carries no
  description at all, so a separate detail call is forced by the API, not taste.
- **`limit` exposed**, default 8.

---

## 1. The tool description

This exact text is what the model reads. It is part of the deliverable, not a
comment. It goes into `TOOL_SPECS`.

```
Search open job postings you have not applied to yet, across every company we
track. Returns the most recently posted matches first, newest to oldest.

Use this to discover roles. Do NOT use it to review applications you have
already sent - that is list_applications. Do NOT use it to read a full job
description - it returns summaries only; call fetch_posting for detail.

This tool does NOT judge whether a role suits you. Call get_profile and decide
that yourself.

`query` matches as a case-insensitive substring over job title and company
name: "AI" matches "Applied AI Engineer", but "ML" will NOT match "Machine
Learning". It does not understand synonyms - search several titles separately
rather than hoping one query covers them.

scope="indexed" (default) searches companies we already track. It is instant.
scope="discover" also searches the wider web for companies we do not track
yet. It is slow and costs money - use it when indexed results look thin.

Read-only. Changes nothing.
```

Notice what that text does: names the sibling tools to use instead, states the
match semantics exactly, warns that synonyms do not work, and declares itself
read-only. That is Lesson 4 §4.4's five questions, answered.

## 2. Parameters

Every one carries its own description. The type says the shape; the description
says the meaning.

| Name | Type | Required | Description |
|---|---|---|---|
| `query` | string | no | Substring matched on job title and company name. Omit to browse everything. |
| `seniority` | enum | no | `junior` \| `mid` \| `senior` \| `staff_plus`. Omit for any. |
| `work_mode` | enum | no | `remote` \| `onsite` \| `hybrid`. Omit for any. |
| `country` | string | no | Country name, e.g. "India". Omit for any. |
| `posted_within_days` | integer | no | Only postings newer than this. |
| `scope` | enum | no | `indexed` (default, fast) \| `discover` (slow, wider). |
| `limit` | integer | no | Default 8, maximum 25. |

**No required parameters at all.** Every one is a filter. An agent that knows
nothing can still call this and get something back — which is what you want on
step one of a run.

`sponsorship` is deliberately **not** a parameter. No ATS exposes it, so we
cannot filter on it honestly. It surfaces as an inferred field in the result
instead, and the agent decides what to do about it.

## 3. The return shape

```json
{
  "showing": 8,
  "matched": 34,
  "note": "Showing 8 of 34. Narrow with query, seniority or country.",
  "today": "2026-09-17",
  "scope": "indexed",
  "results": [
    {
      "posting_id": "job_0041",
      "company": "Vantara Labs",
      "title": "Applied AI Engineer",
      "seniority": "mid",
      "work_mode": "remote",
      "location": "Remote (India)",
      "country": "India",
      "requires_relocation": false,
      "days_since_posted": 3,
      "url": "https://example.test/jobs/job_0041",
      "source": "ashby"
    }
  ]
}
```

Why each envelope field exists:

- **`matched` alongside `showing`** — truncation must be visible. Returning 8 of
  34 silently makes the model believe there are 8.
- **`note`** — tells it what to do about the truncation, in words.
- **`today`** — the model has no clock.
- **`scope`** — so it knows whether it searched narrowly or widely.

And per result:

- **`days_since_posted`, not a timestamp.** Lesson 4 §4.6: anything the model
  calculates, it eventually calculates wrong.
- **`requires_relocation` as a real boolean**, inferred from country and
  work_mode — not prose the model has to interpret.
- **`country` separate from `location`**, because location strings are free text
  and messy (one real Greenhouse row came back as `"Bangalore "`, with a
  trailing space).
- **`source`** — which ATS it came from. Useful when a field is missing because
  that provider does not expose it.

## 4. Ordering

`posted_at DESC, posting_id ASC`. The id tiebreak is not decoration — without
it, two postings sharing a timestamp can swap order between runs, and an
unrepeatable run cannot be graded.

## 5. Errors

Errors go into the model's context and become instructions. Write them as prose
for the agent.

| Situation | Message |
|---|---|
| `limit` above 25 | `"limit must be between 1 and 25; got 40. Using 25."` — clamp, warn, still return results |
| Bad enum | `"seniority must be one of junior, mid, senior, staff_plus; got 'lead'."` |
| No matches | **Not an error.** Return `matched: 0` with a note suggesting broader terms |
| `scope="discover"` unavailable | `"Discovery is unavailable (no search backend configured). Showing indexed results only."` — degrade, do not fail |

The pattern: never fail where you can degrade, and always name the recovery.

## 6. Normalised `Posting`

The adapter's job is to turn three provider shapes into one. These field names
are observed from real API calls, not guessed:

| Our field | Greenhouse | Lever | Ashby |
|---|---|---|---|
| `title` | `title` | `text` | `title` |
| `url` | `absolute_url` | `hostedUrl` | `jobUrl` |
| posted at | `first_published` | `createdAt` | `publishedAt` |
| `location` | `location.name` | `categories.location` | `location` |
| `work_mode` | *(absent — infer)* | `workplaceType` | `isRemote` + `workplaceType` |
| description | *(absent in list)* | `descriptionPlain` | `descriptionPlain` |

`seniority` is inferred from the title for all three — no provider exposes it.

## 7. Ground truth — what "qualifies"

Used by the grader, not by this tool. It lives here because it decides which
fields `search_postings` must return.

A posting qualifies when **all** hold:

1. **Title in the target family** — matched against a keyword list you own
2. **Seniority is `mid` or `senior`** — excludes staff, principal, director
3. **Reachable from India** — country is India, OR work_mode is remote and the
   posting does not require relocation
4. **No visa sponsorship needed** — i.e. `requires_relocation` is false

Rules 3 and 4 overlap deliberately: a globally-remote role open to India
qualifies; a San Francisco on-site role does not.

## 8. What you are implementing

1. A `Posting` dataclass with the fields above
2. `normalise_greenhouse` / `_lever` / `_ashby` — three adapters into `Posting`
3. `infer_seniority(title)` and `infer_work_mode(...)`
4. `SimBackend._search_postings(...)` — filters, ordering, bounding, envelope
5. The `TOOL_SPECS` entry carrying the description text from §1
6. `qualifies(posting, profile)` — the ground-truth rule from §7

Run `pytest tests/test_search_postings.py` and work down the failures.
