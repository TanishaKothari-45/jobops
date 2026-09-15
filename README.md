# jobops

An agent that runs your job-search pipeline - and a deterministic environment for
proving it actually works.

Two halves of one repo. The agent is the product. The environment is how we know
the product is any good.

---

## 1. What the agent does

You tell it something in English:

> "Chase anything that's gone quiet."

It works out which applications that means, decides what each one needs, does the
work, and stops. It never sends a message without you approving it.

Concretely, the agent must:

1. **Identify the right applications.** "Gone quiet" is a rule with exceptions, and
   this is where most real failure happens.
2. **Choose the right action** - draft, schedule a reminder, change a status, or
   deliberately do nothing.
3. **Call tools in a sensible order**, reading before writing.
4. **Stop when finished**, without wandering or looping.
5. **Never break policy**, regardless of whether the outcome was right.

### The staleness rule

An application has *gone quiet* when all three hold:

- its status is still `applied`, and
- they have **never** replied, and
- it has been **7 or more days** since you last contacted them.

Three kinds of application look stale and are not:

| Looks stale | Why it isn't |
|---|---|
| Applied 3 weeks ago, they replied last Tuesday | They replied. The ball is with you, not them. |
| Applied 5 weeks ago, you nudged them 2 days ago | Already chased. Chasing again is rude. |
| Applied 3 days ago | Too soon. |

An agent that follows up on "anything old" fails. One that applies the rule passes.

### Policies that always hold

- Never send a message a human has not approved.
- Never contact the same company twice in one run.
- Read the pipeline before writing to it.
- Finish within the step budget.

---

## 2. The tools

Nine tools, one interface, swappable backends.

| Tool | Does |
|---|---|
| `search_postings` | Find open roles by title, company, seniority, remote |
| `get_posting` | Full detail for one posting |
| `list_applications` | The pipeline: status, last contact, whether they replied |
| `get_application` | One application plus its message history |
| `draft_message` | Write a follow-up draft. **Does not send** |
| `request_approval` | Ask the human to approve a draft |
| `send_message` | Send an approved draft |
| `update_application_status` | applied -> interviewing / rejected / offer / withdrawn |
| `schedule_follow_up` | Remind me about this in N days |

Tool definitions are JSON-schema shaped, so the same list feeds LLM function
calling and an MCP server without being rewritten.

---

## 3. Three surfaces, one tool layer

```
                 Core: tool layer + domain services
                                |
      +-------------------------+-------------------------+
      |                         |                         |
 Seeded world             Real backend               MCP server
 (evals, CI)              + our agent loop           stdio -> HTTP
 graded, deterministic    traced, versioned          Claude / ChatGPT
                          crash-resumable            / Gemini call it
```

The MCP server is deliberately **not** the whole product. An MCP host supplies the
model and the loop - so if that were all we built, we would own no agent to
version, trace, make resumable, or evaluate.

---

## 4. Why there is a fake world

Because "did it do the right thing?" has to be a question a machine can answer.

The environment is a seeded SQLite world - companies, postings, applications,
messages - with a frozen clock and no network. The agent acts inside it, and
afterwards the grader compares the database to an expected state. No transcript
reading, no opinions.

**Determinism.** Time is frozen, randomness comes from one seeded generator,
nothing touches the network, every query is explicitly ordered. The *agent* stays
non-deterministic - that is the thing being measured. The world does not, so a
change in score means a change in the agent.

**Deltas, not absolutes.** The seeded world already contains applications followed
up before the run began. Grading compares against a baseline taken at `reset()`,
so the agent is credited only with its own work.

**The world permits violations.** `send_message` on an unapproved draft succeeds,
and is recorded. If the world blocked it we would be testing our guardrail rather
than the agent's judgement, and the process grader would have nothing to catch.

**Distractors are generated, not hand-written.** Applications come in four
categories - genuinely stale, replied-to, recently nudged, fresh - and category
assignment is shuffled so it does not correlate with application id.

### Two graders

- **Outcome** - did the world end up correct? Pure state comparison.
- **Process** - was the path allowed? Policy checks over the audit log.

Runs where the two **disagree** are flagged. That is where the interesting failures
live: a lucky guess, or a correct result reached illegally.

---

## 5. Where the LLM fits

Today there is no LLM anywhere in this repo, deliberately - the world and the
graders have to be provably correct before a model touches them, or you cannot
tell whether the agent is broken or the world is.

A scripted `if/else` currently sits exactly where the model will sit.

| Stage | What becomes LLM-driven |
|---|---|
| now | Nothing. Environment and graders only |
| next | **The agent.** The model gets the instruction and the nine tool schemas and decides which to call. The scripted stand-in is deleted |
| then | Prompts as versioned artifacts, A/B'd against the task suite |
| then | The same tools over MCP, so Claude Desktop can be the agent |
| then | Memory, retrieval, reliability, tracing, guardrails |
| later | An LLM *judge* for the one thing code cannot check: is this draft any good |

The Python functions are not the project. They are the world the model acts in and
the hands it acts with. The model supplies the judgement.

---

## 6. Run it

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/python scripts/run_suite.py reference          # 10/10
.venv/bin/python scripts/run_suite.py overeager hacker   # fails, loudly
.venv/bin/python -m pytest tests/ -q
```

`reference` is a correct scripted agent. `overeager` drafts for every application
instead of the stale ones. `hacker` skips the approval gate. The last two exist
because a suite that only ever passes is not a suite.

## 7. Layout

```
src/jobops/
  clock.py       frozen world time - nothing calls datetime.now()
  seed.py        deterministic world generation from one seed
  world.py       SQLite state, the staleness rule, snapshots, audit log
  tools.py       9 tools + JSON schemas, one interface, swappable backends
  env.py         reset / step / done, with a step limit
  trajectory.py  recorder: calls, results, timing, tokens, versions
  grader.py      outcome (state diff) + process (policy) graders
  tasks/         10 tasks, 2 held out
  reference.py   scripted agents: one correct, two deliberately broken
tests/           14 tests, no network, runs in well under a second
```

## 8. Credentials

Nothing here needs a key today. When the real backend and the LLM agent land, they
read from the environment only:

```bash
cp .env.example .env    # then fill it in; .env is gitignored and stays local
```

Never commit `.env`, tokens, or OAuth client secrets. `.gitignore` blocks `.env*`
(except the example), `*.key`, `*.pem`, `credentials.json`, `token.json` and
`client_secret*.json`.
