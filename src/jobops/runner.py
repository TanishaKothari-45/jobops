"""Run a policy over a task suite and report."""

from __future__ import annotations

from typing import Callable

from .env import Environment
from .tasks import TASKS


def run_task(task: dict, policy: Callable[[Environment], None], save: bool = False) -> dict:
    env = Environment(task)
    env.reset()
    policy(env)
    report = env.grade()
    if save:
        report["trajectory_path"] = str(env.trajectory.save())
    return report


def run_suite(policy: Callable[[Environment], None], tasks: list[dict] | None = None,
              save: bool = False) -> list[dict]:
    return [run_task(t, policy, save=save) for t in (tasks if tasks is not None else TASKS)]


def summarise(reports: list[dict]) -> dict:
    n = len(reports)
    return {
        "tasks": n,
        "passed": sum(r["passed"] for r in reports),
        "outcome_score": round(sum(r["outcome"]["score"] for r in reports) / n, 3) if n else 0.0,
        "process_score": round(sum(r["process"]["score"] for r in reports) / n, 3) if n else 0.0,
        "disagreements": sum(r["disagreement"] for r in reports),
    }
