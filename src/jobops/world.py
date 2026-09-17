"""The world itself: a SQLite database plus the frozen clock.

The World owns state. It knows nothing about agents, tools or grading - those
sit on top of it. Keeping it this dumb is what makes it resettable and
assertable.
"""

from __future__ import annotations

import json
import sqlite3
from importlib import resources
from pathlib import Path

from .clock import WORLD_EPOCH, Clock, days_between, fmt
from .postings import Posting
from .seed import WorldSetup, generate


class World:
    def __init__(self, seed: int, setup: WorldSetup) -> None:
        self.seed = seed
        self.setup = setup
        self.clock = Clock(WORLD_EPOCH)
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._build()

    # ----------------------------------------------------------------- build

    def _schema(self) -> str:
        return resources.files("jobops").joinpath("schema.sql").read_text()

    def _build(self) -> None:
        self.conn.executescript(self._schema())
        data = generate(self.seed, self.setup, self.clock)

        self.conn.execute(
            "INSERT INTO profile VALUES (?,?,?,?,?,?,?,?,?,?)", data.profile)
        self.conn.executemany(
            "INSERT INTO companies VALUES (?,?,?,?,?,?,?,?,?,?,?)", data.companies)
        self.conn.executemany(
            "INSERT INTO postings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", data.postings)
        self.conn.executemany(
            "INSERT INTO applications VALUES (?,?,?,?,?,?,?,?)", data.applications)
        self.conn.executemany(
            "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)", data.messages)
        self.conn.executemany(
            "INSERT INTO world_meta VALUES (?,?)",
            [("seed", str(self.seed)),
             ("now", self.clock.iso()),
             ("staleness_days", str(self.setup.staleness_days))],
        )
        self.conn.commit()

    def reset(self) -> "World":
        """Rebuild from the seed. Cheaper and safer than mutating back."""
        self.conn.close()
        return World(self.seed, self.setup)

    # ----------------------------------------------------------------- query

    def q(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params))

    def one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def now(self) -> str:
        return self.clock.iso()

    def is_stale(self, app: sqlite3.Row) -> bool:
        """The rule, defined once, used by tools, tasks and graders alike."""
        if app["status"] != "applied":
            return False
        if app["last_inbound_at"] is not None:
            return False
        reference = app["last_outbound_at"] or app["applied_at"]
        return days_between(reference, self.now()) >= self.setup.staleness_days

    def stale_application_ids(self) -> list[str]:
        rows = self.q("SELECT * FROM applications ORDER BY id")
        return [r["id"] for r in rows if self.is_stale(r)]

    def profile(self) -> dict:
        """The one profile row, as a plain dict with JSON columns decoded."""
        row = self.one("SELECT * FROM profile WHERE id = 1")
        return {
            "name": row["name"],
            "headline": row["headline"],
            "years_experience": row["years_experience"],
            "home_country": row["home_country"],
            "max_seniority": row["max_seniority"],
            "open_to_remote": bool(row["open_to_remote"]),
            "needs_sponsorship": bool(row["needs_sponsorship"]),
            "skills": json.loads(row["skills_json"]),
            "target_titles": json.loads(row["target_titles_json"]),
        }

    def open_postings(self, *, applied_to: bool = False) -> list[Posting]:
        """Postings as `Posting` objects, for the pure search function.

        By default this excludes roles we have already applied to - the tool
        promises "postings you have not applied to yet", and the promise is
        kept here rather than left to the agent.
        """
        rows = self.q(
            "SELECT p.*, c.name AS company FROM postings p "
            "JOIN companies c ON c.id = p.company_id "
            "WHERE p.status = 'open' ORDER BY p.id")
        applied = {r["posting_id"] for r in self.q("SELECT posting_id FROM applications")}
        out = []
        for r in rows:
            if not applied_to and r["id"] in applied:
                continue
            out.append(Posting(
                posting_id=r["id"], company=r["company"], title=r["title"],
                seniority=r["seniority"], work_mode=r["work_mode"],
                location=r["location"], country=r["country"],
                requires_relocation=bool(r["requires_relocation"]),
                posted_at=r["posted_at"], url=r["url"], source=r["source"],
            ))
        return out

    # ----------------------------------------------------------------- write

    def record_event(self, tool: str, args: dict, ok: bool, result: object) -> None:
        self.conn.execute(
            "INSERT INTO events (ts, tool, args_json, ok, result_json) VALUES (?,?,?,?,?)",
            (self.now(), tool, json.dumps(args, sort_keys=True), int(ok),
             json.dumps(result, sort_keys=True, default=str)),
        )
        self.conn.commit()

    def events(self) -> list[sqlite3.Row]:
        return self.q("SELECT * FROM events ORDER BY seq")

    # -------------------------------------------------------------- snapshot

    def snapshot(self) -> dict:
        """The final state, reduced to plain values a grader can compare.

        This is the outcome grader's input. Everything here is a count or a
        sorted list, never a timestamp or an id that depends on run order.
        """
        drafts = self.q(
            "SELECT * FROM messages WHERE direction='outbound' AND state IN ('draft','approved') ORDER BY id")
        sent = self.q(
            "SELECT * FROM messages WHERE direction='outbound' AND state='sent' ORDER BY id")
        followed = self.q(
            "SELECT id FROM applications WHERE follow_up_count > 0 ORDER BY id")
        by_status = self.q(
            "SELECT status, COUNT(*) AS n FROM applications GROUP BY status ORDER BY status")

        return {
            "drafts_created": len(drafts),
            "emails_sent": len(sent),
            "applications_followed_up": [r["id"] for r in followed],
            "drafted_for_applications": sorted({r["application_id"] for r in drafts}),
            "application_status_counts": {r["status"]: r["n"] for r in by_status},
            "scheduled_follow_ups": len(self.q(
                "SELECT id FROM applications WHERE next_follow_up_at IS NOT NULL")),
            # The shortlister's answer, as state. This is what makes "are these
            # the right roles?" a set comparison instead of a judgement call.
            "shortlisted": [r["posting_id"] for r in self.q(
                "SELECT posting_id FROM shortlist ORDER BY posting_id")],
            "shortlist_size": len(self.q("SELECT posting_id FROM shortlist")),
            "shortlisted_companies": sorted({r["company"] for r in self.q(
                "SELECT c.name AS company FROM shortlist s "
                "JOIN postings p ON p.id = s.posting_id "
                "JOIN companies c ON c.id = p.company_id")}),
        }

    def dump(self, path: str | Path) -> None:
        """Write the world to a file, for debugging a run by hand."""
        dest = sqlite3.connect(str(path))
        with dest:
            self.conn.backup(dest)
        dest.close()
