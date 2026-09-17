-- The seeded world. Every timestamp is an ISO-8601 UTC string ("2026-09-14T09:00:00Z")
-- so lexicographic ordering is also chronological ordering.

CREATE TABLE world_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Exactly one row. The agent reads this to judge fit for itself - deliberately
-- a tool rather than something baked into search, so the judgement is visible.
CREATE TABLE profile (
    id                 INTEGER PRIMARY KEY CHECK (id = 1),
    name               TEXT NOT NULL,
    headline           TEXT NOT NULL,
    years_experience   INTEGER NOT NULL,
    home_country       TEXT NOT NULL,
    max_seniority      TEXT NOT NULL,
    open_to_remote     INTEGER NOT NULL DEFAULT 1,
    needs_sponsorship  INTEGER NOT NULL DEFAULT 1,
    skills_json        TEXT NOT NULL,
    target_titles_json TEXT NOT NULL
);

CREATE TABLE companies (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    domain         TEXT NOT NULL,
    industry       TEXT NOT NULL,
    headcount      INTEGER,
    funding_stage  TEXT,          -- seed | series_a | series_b | series_c | public | unknown
    last_round_usd INTEGER,
    last_round_at  TEXT,
    ats_provider   TEXT,          -- greenhouse | lever | ashby
    ats_slug       TEXT,
    watched        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE postings (
    id                  TEXT PRIMARY KEY,
    company_id          TEXT NOT NULL REFERENCES companies(id),
    title               TEXT NOT NULL,
    seniority           TEXT NOT NULL,
    location            TEXT NOT NULL,
    country             TEXT,
    work_mode           TEXT NOT NULL DEFAULT 'onsite',
    requires_relocation INTEGER NOT NULL DEFAULT 0,
    remote              INTEGER NOT NULL DEFAULT 0,
    posted_at           TEXT NOT NULL,
    url                 TEXT NOT NULL,
    source              TEXT NOT NULL DEFAULT 'seed',
    description         TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE applications (
    id                TEXT PRIMARY KEY,
    posting_id        TEXT NOT NULL REFERENCES postings(id),
    status            TEXT NOT NULL,
    applied_at        TEXT NOT NULL,
    last_outbound_at  TEXT,
    last_inbound_at   TEXT,
    follow_up_count   INTEGER NOT NULL DEFAULT 0,
    next_follow_up_at TEXT
);

CREATE TABLE messages (
    id             TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id),
    direction      TEXT NOT NULL,          -- outbound | inbound
    subject        TEXT NOT NULL,
    body           TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    state          TEXT NOT NULL,          -- draft | approved | sent | received
    approved_at    TEXT,
    sent_at        TEXT
);

-- The shortlister's answer, as STATE rather than prose. This is what makes the
-- agent gradeable without a judge: "are these the right roles" becomes a set
-- comparison instead of someone reading a paragraph.
CREATE TABLE shortlist (
    posting_id TEXT PRIMARY KEY REFERENCES postings(id),
    reason     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- World-level audit log. Every tool call lands here, successful or not.
-- This is what the process grader reads.
CREATE TABLE events (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    tool        TEXT NOT NULL,
    args_json   TEXT NOT NULL,
    ok          INTEGER NOT NULL,
    result_json TEXT NOT NULL
);

CREATE INDEX idx_postings_company ON postings(company_id);
CREATE INDEX idx_postings_status ON postings(status);
CREATE INDEX idx_applications_status ON applications(status);
CREATE INDEX idx_messages_application ON messages(application_id);
