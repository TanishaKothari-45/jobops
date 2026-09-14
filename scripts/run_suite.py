#!/usr/bin/env python
"""Run every scripted agent over the full task suite."""

from __future__ import annotations

import sys

from jobops.reference import AGENTS
from jobops.runner import run_suite, summarise
from jobops.tasks import TASKS


def main(names: list[str]) -> int:
    failures = 0
    for name in names:
        reports = run_suite(AGENTS[name], TASKS)
        print(f"\n=== {name} " + "=" * (52 - len(name)))
        for r in reports:
            mark = "PASS" if r["passed"] else "FAIL"
            flag = "  <- graders disagree" if r["disagreement"] else ""
            print(f"  {mark}  {r['task_id']:<28} "
                  f"outcome {r['outcome']['passed']}/{r['outcome']['total']}  "
                  f"process {r['process']['passed']}/{r['process']['total']}  "
                  f"steps {r['steps']}{flag}")
            if not r["passed"]:
                for c in r["outcome"]["checks"]:
                    if not c["passed"]:
                        print(f"          outcome.{c['check']}: expected {c['expected']!r}, got {c['actual']!r}")
                for c in r["process"]["checks"]:
                    if not c["passed"]:
                        print(f"          policy.{c['policy']}: {c['detail']}")
        s = summarise(reports)
        print(f"  -> {s['passed']}/{s['tasks']} passed | outcome {s['outcome_score']} | "
              f"process {s['process_score']} | disagreements {s['disagreements']}")
        if name == "reference" and s["passed"] != s["tasks"]:
            failures = 1
    return failures


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["reference"]))
