"""The environment: reset / step / done.

The shape every environment codebase uses. Three ideas only - rebuild the world,
take one action, know when to stop.
"""

from __future__ import annotations

import time
from typing import Any

from .seed import WorldSetup
from .tools import TOOL_SPECS, SimBackend, ToolError
from .trajectory import Trajectory
from .world import World

DEFAULT_STEP_LIMIT = 25


class Environment:
    def __init__(self, task: dict, step_limit: int = DEFAULT_STEP_LIMIT) -> None:
        self.task = task
        self.task_id = task["id"]
        self.seed = task["seed"]
        self.setup = WorldSetup.from_dict(task.get("setup"))
        self.step_limit = task.get("step_limit", step_limit)

        self.world: World | None = None
        self.backend: SimBackend | None = None
        self.trajectory: Trajectory | None = None
        self.baseline: dict = {}
        self.done = False
        self.stop_reason = ""

    # ------------------------------------------------------------------ api

    def reset(self) -> dict:
        """Rebuild the world from the seed and hand back the opening view."""
        self.world = World(self.seed, self.setup)
        self.backend = SimBackend(self.world)
        self.baseline = self.world.snapshot()
        self.done = False
        self.stop_reason = ""
        self.trajectory = Trajectory(task_id=self.task_id, seed=self.seed)
        self.trajectory.start_state = dict(self.baseline)
        return self.observation()

    def observation(self) -> dict:
        """What the agent can see before acting. Deliberately thin - the agent
        has to use tools to learn anything, exactly as in production."""
        assert self.world is not None
        return {
            "instruction": self.task["instruction"],
            "today": self.world.now(),
            "tools": [s["name"] for s in TOOL_SPECS],
            "steps_taken": len(self.trajectory.steps) if self.trajectory else 0,
            "steps_remaining": self.step_limit - (len(self.trajectory.steps) if self.trajectory else 0),
        }

    def step(self, tool: str, args: dict | None = None, thought: str | None = None) -> dict:
        """One action. Returns what the agent sees back, never raises for a
        tool-level failure - a failing tool is information, not a crash."""
        if self.done:
            raise RuntimeError("run is over; call reset() first")
        assert self.backend is not None and self.trajectory is not None

        args = args or {}
        started = time.perf_counter()
        try:
            result: Any = self.backend.call(tool, args)
            ok = True
        except ToolError as exc:
            result, ok = {"error": str(exc)}, False

        self.trajectory.add(
            tool=tool, args=args, ok=ok, result=result,
            world_time=self.world.now(),
            wall_ms=(time.perf_counter() - started) * 1000,
            thought=thought,
        )

        if len(self.trajectory.steps) >= self.step_limit:
            self.finish("step_limit")

        return {"ok": ok, "result": result, **self.observation()}

    def finish(self, reason: str = "agent_stopped") -> None:
        """End the run. `reason` becomes a failure category later."""
        if self.done:
            return
        assert self.world is not None and self.trajectory is not None
        self.done = True
        self.stop_reason = reason
        self.trajectory.stop_reason = reason
        self.trajectory.end_state = self.world.snapshot()

    # ------------------------------------------------------------- grading

    def grade(self) -> dict:
        from .grader import grade_run

        if not self.done:
            self.finish("graded_without_stopping")
        assert self.world is not None and self.trajectory is not None
        report = grade_run(self.task, self.world, self.baseline, self.trajectory)
        self.trajectory.grade = report
        return report
