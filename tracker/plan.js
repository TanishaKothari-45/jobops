// The 45-day plan: Thu 17 Sep -> Sat 31 Oct 2026.
// Each day names its build work explicitly. Recurring items are generated
// from the weekday so the plan stays short and the day stays full.

const WEEKS = [
  { n: 1, range: "17 - 20 Sep", goal: "Graders upgraded, the model plugged in",
    why: "The scripted stand-in gets deleted. First real score on the board." },
  { n: 2, range: "21 - 27 Sep", goal: "Agent working, MCP server in daily use",
    why: "From here you use your own tool layer every day inside Claude Desktop." },
  { n: 3, range: "28 Sep - 4 Oct", goal: "Published to the Environments Hub",
    why: "The public artifact that unlocks the RL-environment marketplaces." },
  { n: 4, range: "5 - 11 Oct", goal: "Memory and context engineering, measured",
    why: "The #2 most-demanded skill in the field, and your biggest gap." },
  { n: 5, range: "12 - 18 Oct", goal: "Reliable, and deployed to real users",
    why: "Answers 'shipped to real users, not just prototypes'. Users need two weeks." },
  { n: 6, range: "19 - 25 Oct", goal: "Observable, guarded, gated in CI",
    why: "Tracing, cost dashboard, approval gates, regression gate." },
  { n: 7, range: "26 - 31 Oct", goal: "Writeup, portfolio, full interview mode",
    why: "The failure taxonomy is the artifact that reads as senior." },
];

// date, week, build task (title + detail). Sundays carry no build work.
const DAYS = [
  ["2026-09-17",1,"Weighted partial credit","Rework grader.py so checks carry weights - 'didn't send unapproved' must outweigh 'subject mentions the role'. You write it, I review."],
  ["2026-09-18",1,"Efficiency + termination scoring","Add steps-used-vs-minimum and stop-reason to the trajectory grade. Then make the four M4 decisions: provider, observation shape, finish signal, malformed-call handling."],
  ["2026-09-19",1,"Agent loop skeleton","Tool schemas to the model, parse the tool call, feed env.step, loop until done or step limit. No cleverness yet."],
  ["2026-09-20",1,null,null],

  ["2026-09-21",2,"First real LLM score","Get the loop passing one task end to end, then run the whole suite. Whatever the number is, it is your baseline."],
  ["2026-09-22",2,"Three seeds and a failure read","Run the suite 3x. Record the spread, not the mean. Read every failed trajectory and find the FIRST wrong step."],
  ["2026-09-23",2,"Prompt versioning","Prompts as files in git. Run two versions against the suite, compare paired, roll one back."],
  ["2026-09-24",2,"Lesson 5 + tool schema fixes","Read the tool-layer lesson, then fix the tool descriptions your failure read exposed. Tool design is prompt design."],
  ["2026-09-25",2,"MCP server over stdio","Same tool layer, new surface. Roughly 150 lines."],
  ["2026-09-26",2,"Wire it into Claude Desktop","Add the server to your config and actually use it on your real job search. Note every friction point - those become tasks."],
  ["2026-09-27",2,null,null],

  ["2026-09-28",3,"Learn the verifiers spec","Read the docs and one real example environment. Plan the port on paper before writing anything."],
  ["2026-09-29",3,"Port part 1 - env and dataset","jobops world and tasks expressed as a verifiers environment."],
  ["2026-09-30",3,"Port part 2 - the verifier","Your outcome and process graders as verifier functions in their interface."],
  ["2026-10-01",3,"Package and document","pyproject, wheel, test a clean install, write the environment's README."],
  ["2026-10-02",3,"PUBLISH to the Environments Hub","Ship it. Then the LinkedIn post writes itself."],
  ["2026-10-03",3,"Apply to the marketplaces","Mercor, Surge, Handshake, Turing, Micro1 - published environment as your evidence."],
  ["2026-10-04",3,null,null],

  ["2026-10-05",4,"Lesson 6 - memory and context","Read it, then decide the design: which memory types, what gets kept, dropped, re-fetched."],
  ["2026-10-06",4,"Memory schema on Postgres","Real Postgres, not SQLite. Schema, indices, migrations."],
  ["2026-10-07",4,"Working memory","Within-run state: what the agent carries between steps, and what it stops carrying."],
  ["2026-10-08",4,"Long-term memory","Across runs: what it remembers about a company, a role, a past conversation. Retrieval over it."],
  ["2026-10-09",4,"Compaction and summarisation","The hard part. What to summarise, when, and how to prove the summary kept what mattered."],
  ["2026-10-10",4,"A/B the memory","Same agent, same suite, with and without memory. This number is the whole module."],
  ["2026-10-11",4,null,null],

  ["2026-10-12",5,"Lesson 7 + idempotency keys","Reliability lesson, then make every write idempotent. No double-sends, ever."],
  ["2026-10-13",5,"Retries and durable run state","Backoff with jitter. Run state in Postgres so a process death is survivable."],
  ["2026-10-14",5,"Crash and resume","Kill the process mid-tool-call. Resume. Prove no duplicate action. This demo is hard to fake and worth a lot."],
  ["2026-10-15",5,"Scheduled runs","The agent wakes daily and chases what has gone quiet, without you asking."],
  ["2026-10-16",5,"DEPLOY","FastAPI + Postgres + Redis, one command, reachable. It does not need to be pretty."],
  ["2026-10-17",5,"Remote MCP + first outside user","Streamable HTTP with OAuth 2.1, then hand the URL to one person."],
  ["2026-10-18",5,null,null],

  ["2026-10-19",6,"Lesson 8 + OTel spans","Observability lesson, then trace a whole agent run properly."],
  ["2026-10-20",6,"Cost and latency dashboard","Three numbers on one screen: cost per task, p95 latency, score."],
  ["2026-10-21",6,"Approval gates","Nothing irreversible happens without a human. Now enforced, not just policy-graded."],
  ["2026-10-22",6,"Injection test suite","Adversarial tasks: untrusted content in tool results trying to steer the agent."],
  ["2026-10-23",6,"CI regression gate","A GitHub Action that blocks a merge when the suite regresses."],
  ["2026-10-24",6,"Retrieval upgrade","Hybrid search plus reranking, with before and after numbers on precision, recall, faithfulness."],
  ["2026-10-25",6,null,null],

  ["2026-10-26",7,"Failure taxonomy","Cluster every failure you have logged into named categories. Count them. This is the artifact."],
  ["2026-10-27",7,"Write the writeup","What broke, why, what the numbers did, what you would do differently."],
  ["2026-10-28",7,"pass^3 and final numbers","Reliability runs, final scores, README rewritten around real results."],
  ["2026-10-29",7,"Final resume rewrite","Every claim now has evidence behind it. Rewrite from scratch, do not patch."],
  ["2026-10-30",7,"Portfolio polish","Repo README, pinned repos, LinkedIn featured section, the environment page."],
  ["2026-10-31",7,"Done - switch modes","Final review. From tomorrow: no building. Interviews, referrals, follow-ups only."],
];
