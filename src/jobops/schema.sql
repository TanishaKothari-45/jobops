-- The seeded world. Every timestamp is an ISO-8601 UTC string ("2026-09-14T09:00:00Z")
-- so lexicographic ordering is also chronological ordering.

CREATE TABLE world_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE companies (
    id       TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    domain   TEXT NOT NULL,
    industry TEXT NOT NULL
);

CREATE TABLE postings (
    id         TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    title      TEXT NOT NULL,
    seniority  TEXT NOT NULL,
    location   TEXT NOT NULL,
    remote     INTEGER NOT NULL DEFAULT 0,
    posted_at  TEXT NOT NULL,
    url        TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE applications (
    id               TEXT PRIMARY KEY,
    posting_id       TEXT NOT NULL REFERENCES postings(id),
    status           TEXT NOT NULL,
    applied_at       TEXT NOT NULL,
    last_outbound_at TEXT,
    last_inbound_at  TEXT,
    follow_up_count  INTEGER NOT NULL DEFAULT 0,
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
CREATE INDEX idx_applications_status ON applications(status);
CREATE INDEX idx_messages_application ON messages(application_id);
