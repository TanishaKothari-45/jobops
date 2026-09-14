# jobops — a deterministic environment for evaluating agents

A simulated job-search operations world that an agent acts inside, built so that
"did it do the right thing?" is a question a machine can answer.

No LLM is involved in the environment or the graders. That is the point: the
world has to be provably correct before a model ever touches it.

## Why it exists

Most agent evaluation is a transcript and an opinion. This is the other kind:
a seeded world with real state, tools that change that state, and graders that
compare the final state to an expected one.

## Run it

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/run_suite.py reference          # should be 10/10
.venv/bin/python scripts/run_suite.py overeager hacker   # should fail, loudly
.venv/bin/python -m pytest tests/ -q
```

## How it fits together

```
clock.py       frozen world time — nothing calls datetime.now()
seed.py        deterministic world generation from one seed
world.py       SQLite state, the staleness rule, snapshots, audit log
tools.py       9 tools + JSON schemas, one interface, swappable backends
env.py         reset / step / done, with a step limit
trajectory.py  black-box recorder: calls, results, timing, tokens, versions
grader.py      outcome (state diff) + process (policy) graders
tasks/         10 tasks, 2 of them held out
reference.py   scripted agents: one correct, two deliberately broken
```

## The design decisions worth knowing

**Determinism.** Time is frozen and seeded, randomness comes from one seeded
generator, nothing touches the network, every query is explicitly ordered. The
agent stays non-deterministic — that is what we are measuring. The world does
not, so a change in score means a change in the agent.

**Deltas, not absolutes.** The seeded world already contains applications that
were followed up before the run began. Grading compares the final state against
a baseline taken at `reset()`, so the agent is only credited with its own work.

**The world permits policy violations.** `send_message` on an unapproved draft
succeeds, and is recorded. If the world blocked it we would be testing our own
guardrail rather than the agent's judgement, and the process grader would have
nothing to catch.

**Distractors are generated, not hand-written.** Applications come in four
categories — genuinely stale, replied-to, recently nudged, and fresh — and the
category assignment is shuffled so it does not correlate with application id.
An agent that pattern-matches on "looks old" fails; one that applies the rule
passes.

**Two graders, and their disagreements.** Outcome grading asks whether the world
ended up right. Process grading asks whether the path was allowed. Runs where
the two disagree are flagged, because that is where the interesting failures
live — a lucky guess, or a correct result reached illegally.

## Status

Project 1 of the Agent Env Lab curriculum. Next: LLM-as-judge for the one slice
code cannot decide, calibrated against hand labels.
