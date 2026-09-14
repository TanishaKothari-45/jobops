"""The black box recorder.

You cannot recover data you did not capture, and you will want it later - in
module M9 the cost and latency analysis reads these files rather than re-running
anything. So record generously and attribute everything.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Step:
    index: int
    tool: str
    args: dict
    ok: bool
    result: Any
    world_time: str
    wall_ms: float
    tokens_in: int = 0
    tokens_out: int = 0
    thought: str | None = None


@dataclass
class Trajectory:
    """One run of one task. Always attributable: task, seed, versions, model."""

    task_id: str
    seed: int
    prompt_version: str = "none"
    model: str = "scripted"
    run_seed: int = 0
    steps: list[Step] = field(default_factory=list)
    start_state: dict = field(default_factory=dict)
    end_state: dict = field(default_factory=dict)
    stop_reason: str = ""
    grade: dict = field(default_factory=dict)

    def add(self, **kwargs) -> Step:
        step = Step(index=len(self.steps), **kwargs)
        self.steps.append(step)
        return step

    @property
    def tool_calls(self) -> list[str]:
        return [s.tool for s in self.steps]

    @property
    def total_tokens(self) -> int:
        return sum(s.tokens_in + s.tokens_out for s in self.steps)

    @property
    def wall_ms(self) -> float:
        return sum(s.wall_ms for s in self.steps)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, directory: str | Path = "trajectories") -> Path:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{self.task_id}__seed{self.seed}__{int(time.time()*1000)}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        return path
