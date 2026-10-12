# Planner — Agentic Repository Simulation Platform

This file is the development contract. The entire product is built from it. Do not invent stages, agents, MCP servers, loops, or memory stores that are not named here. Do not skip a named piece without updating this file first. This planner contains no implementation code.

---

## 1. Purpose

Turn a repository (clone or upload) into a **verified, replayable simulation**: a knowledge graph of the system, candidate and observed paths, coverage with reasons, documents, diagrams, and a UI that can replay what actually ran.

The system is autonomous. A supervisor routes work through seven stages. Three retry loops repair builds, repair scenarios, and chase coverage. Agents never touch tools, files, databases, or the sandbox directly. They call in-process tool modules (the MCP doors). Every claim has provenance. A job that cannot finish cleanly ends as **completed with gaps**, with reasons listed.

**Who it is for:** the builder of this platform, and anyone who needs to understand how a repository becomes a verified simulation.

---

## 2. How to use this planner

- Build in the milestone order in section 16. Each milestone must produce something you can inspect without the next stage.
- When a ticket is written, it must name the stage, the subagent or service, the tool modules it may call, and the Postgres memory it reads and writes.
- When two designs conflict, this file wins. Change this file, then change the code.
- Frontend, backend, and worker must share the same job state and the same memory model. Do not keep a second source of truth.
- Do not put secrets, raw traces, or whole modules into LLM context. Follow the token and evidence rules in section 12.

---

## 3. Product shape

A full-stack application:

- **Frontend:** interactive app for starting jobs, watching progress, approving gates, browsing the graph, replaying traces, and reading reports.
- **Backend API:** accepts jobs, serves job state, graph, coverage, reports, and approval actions.
- **Worker:** runs the supervisor and stage graph for each job.
- **Postgres + pgvector:** long-term agentic memory, knowledge graph, embeddings, job checkpoints, audit, and indexed traces.
- **Sandbox:** isolated Docker network per job for build, run, mocks, and traffic. No internet during the run phase.
- **LLM adapter:** one interface to hosted Groq models and local Ollama models and embeddings.

A job is the unit of work. One job = one repository snapshot + one run of the seven-stage flow (with loops). The user can pause, approve, resume, and inspect a job at any checkpoint.

---

## 4. Locked stack

These choices are locked unless this planner is updated.

| Concern | Choice | Why |
|---|---|---|
| API | FastAPI | Job API, approvals, report download, worker health |
| Orchestration | LangGraph-style state machine on a worker process | Supervisor + stages + loops; Postgres checkpointer, not Temporal |
| Frontend | React | Job console + React Flow replay UI |
| System of record | PostgreSQL | Jobs, checkpoints, graph, memory, audit, coverage, approvals |
| Vectors | pgvector in the same Postgres | Semantic search over code and summaries without a second vector DB |
| Queue / rate counters | Redis | Worker queue and Groq/Ollama rate-limit counters |
| Blobs | MinIO (S3 API) | Snapshots, raw traces, reports, replay packages |
| Graph queries | Postgres recursive queries over node/edge tables | Replaces Neo4j/Cypher for v1. Same semantics, one database |
| Traces | OpenTelemetry collector + Jaeger (or Tempo) | Runtime proof. Span index also lives in Postgres |
| Agent observability | Self-hosted Langfuse | Agent traces and token cost |
| Local models | Ollama | Tier C summaries and embeddings |
| Hosted models | Groq free-tier open models | Tier A and B |
| Sandbox | Docker network per job | Later: Firecracker or a managed sandbox |
| Secrets scan | gitleaks, trufflehog | Intake only; findings masked everywhere after |

**Not in v1:** Neo4j, Qdrant, Temporal, Firecracker, selling the product (revisit Neo4j Community GPL only if a graph engine is added later).

---

## 5. Architecture (one picture in words)

```
User (React UI)
    -> FastAPI
         -> Postgres (jobs, memory, graph, vectors, audit)
         -> Redis (enqueue)
         -> MinIO (signed URLs for blobs)
    -> Approval actions write to Postgres; worker resumes

Worker
    -> Supervisor (rules first, LLM only when rules cannot decide)
         -> seven bands in order, with loops A / B / C
    -> LLM adapter (Groq / Ollama)
    -> 13 tool modules inside the worker (same names as the MCP doors)
         -> tools, sandbox, Postgres-backed graph/search, files, mocks, traces, reports

Shared memory (Postgres + MinIO)
    -> every stage reads and writes here
    -> supervisor state holds only identifiers, counters, metrics
```

**How to read the flow**

- Top to bottom: job request enters the supervisor, then Intake → Analysis → Flow tracer → Environment → Simulation → Verifier → Reporter.
- In each band, left side is subagents. Same-step letters (2a, 2b) run in parallel.
- Right side is tool modules and tools. Agents reach tools only through those modules.
- Filled / LLM boxes call the LLM adapter. Plain boxes are deterministic code. Dashed boxes are running systems or decision points.
- Loops on the left: A build-repair, B scenario-repair, C coverage.
- Supervisor regains control after every band.
- Every band writes what it learns to shared memory.

---

## 6. Long-term agentic memory (Postgres + pgvector)

This is the core of the product. Memory is not chat history. Memory is the durable, queryable, provenanced record of what the system learned, tried, observed, and still does not know.

### 6.1 Memory kinds

| Kind | Lives in | Purpose |
|---|---|---|
| Working / job state | Postgres job + checkpoint tables | Current stage, loop counters, tier, next action, budget |
| Episodic | Postgres events + Langfuse | What the supervisor and subagents did, in order |
| Semantic | pgvector + summary rows | Embeddings of functions, files, modules, subsystems, gaps |
| Graph | Postgres nodes + edges | The system model: modules, functions, endpoints, tables, paths |
| Evidence | Postgres + MinIO | File/line ranges, span IDs, raw logs, raw traces |
| Coverage | Postgres coverage + gap rows | What is summarized, exercised, mocked, blocked, unverified |
| Policy | Postgres prompt registry + allow-lists | Which tools an agent may call; which prompts are active |
| Human | Postgres approvals | Paused questions and answers |

### 6.2 Graph model (relational, same meaning as the original Cypher graph)

**Node types:** Module, Function, Class, Endpoint, Table, Column, Queue, Job (scheduled/consumer job), ExternalService, ConfigKey, Path, Scenario, File.

**Edge types:** CONTAINS, IMPORTS, CALLS, EXPOSES, READS, WRITES, OBSERVED_IN, EXERCISED_BY, and the related edges needed to walk endpoint → tables / queues / external calls.

**Every node and edge carries provenance**

- source: `static` | `llm` | `runtime`
- confidence: numeric
- evidence: file + line range, or trace + span IDs
- job_id and snapshot_id

A node counts as **covered** only when it has a summary **and** a file and line reference.

### 6.3 Vector model

- One embedding table keyed by `(job_id, object_type, object_id, content_hash)`.
- Local embedding model via the LLM adapter. Search costs nothing.
- Hybrid search: pgvector similarity plus Postgres full-text. This is what `search-mcp` wraps.
- Summaries are cached by file hash. An unchanged file is never summarized twice.

### 6.4 What the supervisor is allowed to hold

Identifiers, counters, metrics only:

- snapshot_id, job_id, tier, loop A/B/C counts
- coverage numbers, last verified-path count
- budget remaining, rate-limit pause flag
- pending approval id

Large payloads stay in Postgres or MinIO. Stages do not pass large data to each other.

### 6.5 Object store (MinIO)

- Repository snapshot (masked)
- Raw OpenTelemetry traces
- Generated docs, diagrams, replay package, coverage report
- Build logs when they are large

Postgres stores the index and pointers. The UI loads blobs through the API.

---

## 7. Supervisor

**Role:** route by state and coverage; regain control after every stage.

**Mode:** deterministic rules first. LLM (tier B) only when rules cannot decide, such as which gap to attack next.

**Routing rules (apply in this order)**

1. No snapshot yet → Intake
2. Unanalyzed nodes remain → Analysis
3. Candidate paths not built → Flow tracer
4. No run plan, or tier unknown → Environment
5. Tier is at least partial dynamic, unexercised paths remain, attempts left → Simulation
6. Fresh traces not yet reconciled → Verifier
7. Coverage goal met, coverage plateaued, or budget reached → Reporter, then end

**Human approval gate:** pause when a missing secret, network access, or destructive action is required. Checkpoint the job. Resume when the user answers. Use `approval-mcp`.

**Cross-cutting (always on)**

- Budget guard
- Rate-limit scheduler
- Context manager
- Approval gate
- Prompt registry
- Prompt filter
- Audit logger

---

## 8. Stages, subagents, MCP, tools

Mode: **LLM** = calls the LLM adapter. **Det** = deterministic code. **System** = running target, not an agent. **Decision** = supervisor choice.

Steps with the same number and a letter run in parallel.

### 8.1 Intake

**Goal:** get the code into a safe, classified snapshot.

| Step | Subagent | Mode | Does | MCP | Tools |
|---|---|---|---|---|---|
| 1 | Source fetcher | Det | Clone or extract upload within size and depth limits | git-mcp, fs-mcp | Git CLI |
| 2 | Secret scanner | Det | Find secrets; mask them in every later output | fs-mcp, graph-mcp | gitleaks, trufflehog |
| 3 | Classifier | Det | Label files (source, test, config, generated, vendored), languages, build systems, frameworks | fs-mcp, graph-mcp | enry, file walker |
| 4 | Stack profiler | LLM | Summarize stack, entry points, likely run commands from README and build files | fs-mcp, graph-mcp | LLM adapter |

**Writes:** snapshot (MinIO), file inventory, masked secret findings, stack profile.

### 8.2 Analysis

**Goal:** understand every module, file, and function, with evidence.

| Step | Subagent | Mode | Does | MCP | Tools |
|---|---|---|---|---|---|
| 1 | Module partitioner | Det | Split the module tree into context-sized units; order by dependency | graph-mcp | import-graph clustering |
| 2 | Code analysts (one per unit, parallel) | LLM | Read parsed symbols; summarize functions, then files, then modules; write to the graph | code-intel-mcp, search-mcp, graph-mcp | tree-sitter, SCIP, LSP, local embeddings, LLM adapter |
| 3a | API extractor | Det | Endpoints, middleware, auth, schemas | code-intel-mcp, graph-mcp | Semgrep rules, framework plugins, OpenAPI parser |
| 3b | Data extractor | Det | Tables, columns, migrations, queries; link code to them | code-intel-mcp, graph-mcp | framework plugins, sqlglot |
| 3c | Jobs and queues extractor | Det | Queues, topics, consumers, scheduled jobs | code-intel-mcp, graph-mcp | framework plugins |
| 3d | Integration and infra extractor | Det | External calls, config keys, feature flags, Dockerfiles, compose, Helm, Terraform, CI | code-intel-mcp, graph-mcp | framework plugins, config parsers |
| 4 | Subsystem synthesizer | LLM | Roll module summaries into subsystem and system narratives and a dependency view | graph-mcp, search-mcp | LLM adapter |

**Writes:** Module, Function, Class, Endpoint, Table, Column, Queue, Job, ExternalService, ConfigKey nodes; CONTAINS, IMPORTS, CALLS, EXPOSES, READS, WRITES and related edges; summaries with file/line evidence; vectors; coverage status per node.

**Small retry:** a failed analysis unit is retried up to 2 times.

### 8.3 Flow tracer

**Goal:** build the candidate paths the simulation will try to prove.

| Step | Subagent | Mode | Does | MCP | Tools |
|---|---|---|---|---|---|
| 1 | Static path builder | Det | Walk from every endpoint, job, and consumer to tables, queues, and external calls; depth limits and cycles | graph-mcp | recursive graph traversals |
| 2 | Dispatch resolver | LLM | Resolve DI, interfaces, reflection, callbacks; record confidence | graph-mcp, code-intel-mcp | SCIP call data, LLM adapter |
| 3 | Path ranker | Det | Rank by fan-out, data sensitivity, centrality | graph-mcp | graph metrics |

**Writes:** ranked Path records (ordered nodes, static confidence). Each path is `static-only` until proven.

### 8.4 Environment

**Goal:** make the application build and run in the sandbox, and report how far it got.

| Step | Subagent | Mode | Does | MCP | Tools |
|---|---|---|---|---|---|
| 1 | Run planner | LLM | Decide how to build and run from stack profile, Dockerfile/compose, CI; set target tier | fs-mcp, graph-mcp | LLM adapter |
| 2a | Dockerfile writer | LLM | Write or edit Dockerfile, compose, entrypoint; add OpenTelemetry instrumentation | fs-mcp | Docker, Compose, OTel agents |
| 2b | Infra provisioner | Det | Start databases, caches, brokers the code uses | sandbox-mcp, db-mcp | Docker Compose, Testcontainers |
| 2c | Mock generator | LLM | Stubs for third-party HTTP and AWS from ExternalService nodes | mock-mcp, graph-mcp | WireMock, LocalStack |
| 3 | Config synthesizer | Det | Env files with fake secrets and local service URLs | fs-mcp, graph-mcp | env templating |
| 4 | Build runner | Det | Build and start; wait for health; collect logs | sandbox-mcp | Docker, BuildKit |
| 5a | Failure diagnoser | LLM | After failed build: root cause + patch; loop A returns to Dockerfile writer | sandbox-mcp, fs-mcp | LLM adapter |
| 5b | Data seeder | LLM + Det | After healthy start: migrations and constraint-valid seed data | db-mcp | Faker |
| 6 | Tier assessor | Det | Classify full dynamic / partial dynamic / static only, with reasons | sandbox-mcp, graph-mcp | health checks |

**Writes:** run plan, build files, env file, mock stubs, seed data, tier + reasons, dependency status (`real` | `mocked` | `unavailable`).

**Loop A:** Failure diagnoser → Dockerfile writer. Design limit 6. Free-setup limit 3. Then drop tier and report why.

### 8.5 Simulation

**Goal:** exercise ranked paths with generated traffic and record what really happens.

| Step | Subagent | Mode | Does | MCP | Tools |
|---|---|---|---|---|---|
| 1 | Scenario planner | LLM | Pick paths, plan scenarios and data needs; revise after each coverage review | graph-mcp | LLM adapter |
| 2a | Request builder | LLM | Valid requests from schemas and seeded IDs, including auth headers | http-mcp, db-mcp | httpx |
| 2b | Workflow chainer | LLM | Order dependent calls; pass IDs and tokens forward | http-mcp | httpx |
| 2c | Fuzzer | Det | Boundary and error cases from OpenAPI | http-mcp | Schemathesis, Hypothesis |
| 2d | UI and event drivers | LLM | Browser flows, queue messages, scheduled jobs, webhooks, CLI | browser-mcp, sandbox-mcp, mock-mcp | Playwright |
| — | App in sandbox | System | Target app with real DBs, mocks, OpenTelemetry. Not an agent | sandbox-mcp | Docker |
| 3a | Scenario repairer | LLM | Adaptation rules on failure; loop B returns to Request builder | http-mcp, db-mcp, mock-mcp | LLM adapter |
| 3b | Trace collector | Det | Collect OTel spans, normalize, link to graph nodes | trace-mcp | OTel collector, Jaeger or Tempo |

**Writes:** scenario records and status; normalized traces and spans (MinIO, indexed in Postgres).

**Loop B adaptation rules**

| Response or event | Action |
|---|---|
| 401 or 403 | Run auth flow or seed a user and token, then retry |
| 404 | Replace path parameters with IDs from seeded data |
| 400 or 422 | Repair payload from validation error and schema |
| 409 | Vary unique fields and retry |
| 5xx | Record with logs, retry once with different data, then mark failed |
| Timeout | Check dependency health, then retry or mark blocked |
| Unmatched mock request | Create a stub and retry |

Design limit 3 attempts per endpoint. Free-setup limit 2.

### 8.6 Verifier

**Goal:** prove what was learned, score coverage, decide what happens next.

| Step | Subagent | Mode | Does | MCP | Tools |
|---|---|---|---|---|---|
| 1a | Claim checker | Det | Check each LLM claim against syntax tree, SCIP, graph; flag or remove unsupported claims | code-intel-mcp, graph-mcp | tree-sitter AST checks |
| 1b | Path reconciler | Det | Compare static paths with traces; label confirmed / newly observed / unexercised; write runtime edges | graph-mcp, trace-mcp | graph diff |
| 1c | Consistency critic | LLM | Summaries must agree across levels (module vs children) | graph-mcp, search-mcp | LLM adapter |
| 2 | Coverage auditor | Det | Coverage of modules, endpoints, tables, external calls; list gaps | graph-mcp | graph queries |
| 3 | Gap analyst | LLM | Explain each gap (missing role, data, flag, unreachable); recommend next action | graph-mcp, trace-mcp | LLM adapter |
| 4 | Supervisor decision | Decision | More scenarios (loop C), re-run Analysis or Environment, or report | graph-mcp | coverage metrics |

**Writes:** OBSERVED_IN and EXERCISED_BY edges, updated confidence, claim verdicts, coverage metrics, gap list with reasons.

**Loop C:** Verifier decision → Scenario planner while unexercised paths remain. Exit when no new verified path for 2 rounds or budget is reached. Design limit 5 rounds. Free-setup limit 3.

**Small retry:** a failed verification pass is retried up to 2 times.

### 8.7 Reporter

**Goal:** package the verified result for people and for the UI.

| Step | Subagent | Mode | Does | MCP | Tools |
|---|---|---|---|---|---|
| 1a | Doc generator | LLM | Architecture overview, module docs, API catalogue, data-model description | graph-mcp, report-mcp | LLM adapter, Markdown export |
| 1b | Diagram generator | Det | Mermaid sequence, ER, component diagrams from graph and traces | report-mcp | Mermaid |
| 1c | Simulation packager | Det | Replay package: graph, layout hints, scenarios, spans | report-mcp, graph-mcp | React Flow JSON export |
| 1d | Coverage reporter | Det | Final report: verified, mocked, unexercised, blocked, with reasons | report-mcp, graph-mcp | Markdown export |

**Writes:** docs, diagrams, replay package, coverage report (MinIO). Opened in the interactive simulation UI.

---

## 9. Tool modules (MCP doors, in-process)

Agents never touch Git, disk, the graph, or the sandbox with raw commands. There are **13 tool modules** inside the worker, still named like MCP doors (`git-mcp`, `fs-mcp`, …). Each wraps real tools. Each agent has an allow-list. Every call is audited. Secrets never appear in tool arguments or results. Sandbox tools reach only the current job’s sandbox. You do **not** start these as separate servers. The worker imports them.

| Server | Tools exposed | Backed by | Used in |
|---|---|---|---|
| git-mcp | clone_repo, checkout, list_files, read_file, diff, log | Git CLI, GitHub and Bitbucket APIs | Intake |
| fs-mcp | read_file, write_file, edit, list, search_text, apply_patch | Job workspace | All stages |
| code-intel-mcp | parse_file, get_symbols, find_definition, find_references, call_graph, run_semgrep | tree-sitter, SCIP, LSP, Semgrep | Analysis, Flow tracer, Verifier |
| graph-mcp | upsert_nodes, upsert_edges, run_traversal, get_coverage, get_subgraph | Postgres graph tables | All stages |
| search-mcp | semantic_search, keyword_search, hybrid_search | pgvector + Postgres full-text | Analysis, Verifier |
| sandbox-mcp | create_sandbox, exec, build, start_service, get_logs, snapshot, destroy | Local Docker network | Environment, Simulation |
| db-mcp | list_tables, describe, run_migration, seed, query_readonly | Databases **inside the sandbox** (target app), not platform Postgres | Environment, Simulation |
| http-mcp | send_request, send_batch, run_schemathesis, record_response | Sandbox network | Simulation |
| browser-mcp | open, click, fill, screenshot, record_flow | Playwright | Simulation |
| trace-mcp | start_collection, get_traces, get_spans, normalize_trace | OTel collector, Jaeger or Tempo | Simulation, Verifier |
| mock-mcp | create_stub, list_stubs, get_unmatched_requests | WireMock, LocalStack | Environment, Simulation |
| report-mcp | render_mermaid, export_markdown, package_simulation | Renderers | Reporter |
| approval-mcp | request_approval, ask_user | UI and notifications | Supervisor approval gate |

`graph-mcp` and `search-mcp` talk to **platform Postgres**. `db-mcp` talks only to **sandbox** databases of the target application.

---

## 10. Tools and systems (complete list)

Git CLI; GitHub / Bitbucket APIs; enry; file walker; gitleaks; trufflehog; tree-sitter; SCIP indexers; LSP servers; Semgrep; OpenAPI parser; sqlglot; framework plugins; config parsers; import-graph clustering; local embeddings; Postgres recursive graph queries; graph metrics; pgvector; Docker; Compose; BuildKit; Testcontainers; WireMock; LocalStack; Faker; env templating; health checks; OpenTelemetry agents and collector; Jaeger or Tempo; httpx; Schemathesis; Hypothesis; Playwright; Mermaid; React Flow JSON export; Markdown export; LLM adapter (Groq + Ollama).

Platform compose services: Postgres, Redis, MinIO, Jaeger, Langfuse, Ollama.

Processes on the machine: FastAPI, the worker, React UI. Tool modules load inside the worker.

---

## 11. What each stage reads and writes

Stages do not pass large data to each other. They read and write shared memory. Supervisor state holds only identifiers, counters, and metrics.

| Stage | Reads | Writes |
|---|---|---|
| Intake | Repository URL or upload, branch, optional hints | Snapshot, file inventory, masked secret findings, stack profile |
| Analysis | Files, symbols, stack profile | Graph nodes and edges listed in 8.2; summaries with evidence; vectors; coverage status |
| Flow tracer | Graph nodes and edges | Path records and ranking |
| Environment | Stack profile, config keys, external-service nodes | Run plan, Dockerfile/compose, env, mocks, seed, tier + reasons, dependency status |
| Simulation | Ranked paths, seeded database, running app | Scenario records and status; normalized traces (MinIO + Postgres index) |
| Verifier | Traces, static graph, summaries | OBSERVED_IN, EXERCISED_BY, confidence, claim verdicts, coverage, gaps |
| Reporter | Verified graph, traces, coverage | Documents, diagrams, replay package, coverage report |

---

## 12. LLM usage

Only named LLM subagents call a model. Everything else is deterministic. The more parsers and rules do, the fewer tokens are used.

### 12.1 Who calls the model

| Stage | LLM-driven subagents | Purpose | Tier |
|---|---|---|---|
| Supervisor | Routing, only when rules cannot decide | Pick the next gap | B |
| Intake | Stack profiler | Stack and run commands | C or B |
| Analysis | Code analysts, Subsystem synthesizer | Function / file / module / system summaries | C bulk, B roll-ups |
| Flow tracer | Dispatch resolver | Indirect calls | B |
| Environment | Run planner, Dockerfile writer, Mock generator, Failure diagnoser, Data seeder | Plan, write, repair | B; A for Failure diagnoser |
| Simulation | Scenario planner, Request builder, Workflow chainer, UI and event drivers, Scenario repairer | Plan, build, repair | B |
| Verifier | Consistency critic, Gap analyst | Cross-check, explain gaps | B |
| Reporter | Doc generator | Write documentation | B or C |

**Tiers**

- **C:** local 7B–14B coder on Ollama. No rate limit. Slow without a GPU.
- **B and A:** hosted open model on Groq free tier (for example gpt-oss-120b or a Qwen model). A is the same model with more attempts.
- **Embeddings:** local model. Search is free.

### 12.2 Limits to design around

Treat Groq sample free-plan numbers as the budget to design for, and always read the live Console page: 30 requests/minute, 1,000 requests/day, 8,000 tokens/minute, 200,000 tokens/day, per organization.

| Constraint | Response |
|---|---|
| 8,000 tokens a minute | Keep every call small. Never feed a whole module at once |
| 200,000 tokens a day | Rate-limit scheduler pauses the job and resumes after reset; checkpoints make this safe |
| Slow local models | Run Tier C in the background while Tier B waits for its window |
| Weaker planning from open models | Supervisor rules first; strict JSON outputs; low loop limits |

**Free-setup loop limits:** loop A = 3, loop B = 2 per endpoint, loop C = 3 rounds.

**Caching:** summaries keyed by file hash.

**Start size:** repositories of 5,000 to 10,000 lines.

---

## 13. Failure handling and result tiers

Every failure has a detector and a defined response. A job that cannot finish cleanly ends as **completed with gaps**, with reasons.

| Failure | Detection | Response |
|---|---|---|
| LLM rate limit or API error | HTTP status, rate-limit headers | Wait, backoff, or fall back to local model |
| Context too large | Token count check | Split units; summarize hierarchically |
| File fails to parse | tree-sitter error nodes | Record unparseable; regex + LLM fallback; keep in coverage report |
| Build fails repeatedly | Loop A counter | Drop to partial-dynamic or static-only; report why |
| App crashes during a scenario | Health check, exit code | Restart service; mark scenario failed with logs |
| Request keeps failing | Loop B counter | Classify blocked / bad data / app bug; move on |
| Coverage stops improving | No new verified path for the set number of loop C rounds | Stop loop; record remaining gaps; report |
| Unsupported claim in a summary | Claim checker | Remove or mark unverified |
| Worker crash | Checkpoint on restart | Resume from last completed node |
| Budget or daily token limit | Budget guard, rate-limit scheduler | Pause and resume later, or finish partial |
| Risky action | Supervisor approval gate | Pause for human approval |

| Result tier | Criteria | User gets |
|---|---|---|
| Full dynamic | App and all required real dependencies run; mocks cover external calls | Verified traces for every exercised path |
| Partial dynamic | Some services run; others stubbed or skipped | Traces for what ran; rest labelled static-only |
| Static only | App cannot start within limits | Graph-based paths labelled unverified, plus why the run failed |

---

## 14. Frontend

One React application. It is not a chat wrapper. It is an operations and replay console.

**Pages / surfaces**

1. **Job start** — repo URL or upload, branch, optional hints, budget defaults.
2. **Job list** — status, tier, coverage, cost, last stage.
3. **Live run** — current band, active subagents, loop counters, logs that are already sanitized.
4. **Approval** — the pause reason, the question, accept / deny / supply a secret via a one-time channel that is never written into agent memory in clear text.
5. **Graph explorer** — nodes and edges from Postgres; filter by type, coverage, source, confidence.
6. **Path and scenario** — ranked paths, scenario status, request/response summaries without secrets.
7. **Trace replay** — React Flow from the replay package; step spans; highlight OBSERVED_IN / EXERCISED_BY.
8. **Reports** — architecture docs, API catalogue, data model, Mermaid diagrams, coverage report.
9. **Memory inspector** — job working state, gap list, claim verdicts, provenance panel (file/line or span).

**UI rules**

- Never show unmasked secrets.
- Always show provenance on a selected node or claim.
- Application state is the job record in Postgres. Every page that shows a job reads the same job_id.
- Replay is driven by the Reporter package, not by a second client-side graph.

---

## 15. Backend

**FastAPI**

- Create job, upload or clone request, list jobs, get job, stream events.
- Graph subgraph, search, coverage, gaps, scenarios, traces index.
- Approvals.
- Signed download of snapshot metadata, reports, replay package.
- Health of worker and compose services.

**Worker**

- One state machine per job: supervisor + seven stages + loops A/B/C.
- Postgres checkpointer. Resume after crash, rate-limit pause, or approval pause.
- Enqueue via Redis. Only one active sandbox worker per job.
- Emit sanitized events the UI can subscribe to.

**Tool modules**

- The thirteen doors in section 9 live as code inside the worker.
- They are not separate processes you start.
- Platform credentials never injected into the sandbox.

**Security**

- Sandbox: separate Docker network per job, no internet in the run phase.
- Run only repositories you trust. Docker is weaker isolation than a microVM.
- Tool allow-lists per agent.
- Audit log of every MCP call.
- Secrets masked at Intake and never rehydrated into LLM prompts or UI.

**Local hardware target:** 16 GB RAM (32 GB better). All platform services via Docker Compose plus processes on the host.

---

## 16. Build order (milestones)

Each step must be checkable on its own. Do not start the next milestone until the previous one has a visible result in the UI or in Postgres.

### M0 — Platform skeleton

- Compose: Postgres (pgvector), Redis, MinIO, Jaeger, Langfuse, Ollama.
- FastAPI hello + job table + checkpoint table.
- React shell with job list and empty job detail.
- Worker that can pick a job and write stage = `accepted`.

**Done when:** creating a job in the UI writes a row and the worker marks it accepted.

### M1 — Intake + graph store

- git-mcp, fs-mcp, graph-mcp.
- Source fetcher, Secret scanner, Classifier (no LLM yet).
- Node/edge tables and file inventory in Postgres.
- Snapshot in MinIO.

**Done when:** a trusted small repo is cloned, secrets are masked, files are labelled, and the graph has File nodes.

### M2 — Analysis without LLM summaries

- code-intel-mcp.
- Module partitioner + extractors 3a–3d (API, data, jobs/queues, integration/infra).
- Symbols and structural edges only.

**Done when:** endpoints, tables, queues, and external services appear as nodes with file/line evidence.

### M3 — LLM summaries + search

- LLM adapter, search-mcp, embeddings in pgvector.
- Stack profiler, Code analysts, Subsystem synthesizer.
- File-hash cache.

**Done when:** a function node has a summary, evidence, an embedding, and hybrid search can find it.

### M4 — Flow tracer

- Static path builder, Dispatch resolver, Path ranker.
- Path records in Postgres, all `static-only`.

**Done when:** ranked paths exist from endpoints/jobs/consumers to tables/queues/external calls.

### M5 — Environment + loop A

- sandbox-mcp, db-mcp, mock-mcp.
- Full Environment band on **one** Python + Postgres sample repository.
- Loop A with free-setup limit 3.
- Tier assessor.

**Done when:** that sample either reaches a healthy app (full or partial dynamic) or exits static-only with reasons.

### M6 — Simulation + traces + loop B

- http-mcp, browser-mcp, trace-mcp.
- Scenario planner through Trace collector.
- Loop B adaptation rules.
- Spans in Jaeger and indexed in Postgres.

**Done when:** at least one scenario produces a normalized trace linked to graph nodes.

### M7 — Verifier + loop C

- Claim checker, Path reconciler, Consistency critic, Coverage auditor, Gap analyst.
- Supervisor decision and loop C (free-setup limit 3).

**Done when:** a path can become confirmed, coverage metrics exist, and a gap has a reason.

### M8 — Reporter + replay UI

- report-mcp.
- Docs, Mermaid, replay package, coverage report.
- Graph explorer, trace replay, reports, memory inspector.

**Done when:** the UI can open the job and replay an exercised path with provenance.

### M9 — Hardening

- Approval gate end to end.
- Rate-limit scheduler and daily pause/resume.
- Budget guard.
- Audit log UI.
- Failure table in section 13 exercised on the sample repo.

**Done when:** a paused job resumes after approval, and a rate-limit pause resumes after a simulated reset.

---

## 17. Definition of done for the product (v1)

A user can submit a trusted 5k–10k line repository and, without writing stage-specific scripts, get:

- a classified, secret-masked snapshot
- a provenanced graph of modules, functions, endpoints, tables, queues, jobs, external services
- ranked paths
- a declared result tier
- zero or more verified traces
- a coverage report that lists verified, mocked, unexercised, and blocked items with reasons
- docs and a replayable UI
- a job that is resumable after crash, rate limit, or approval

All agent tool use went through the 13 in-process tool modules. Platform memory lived in Postgres + pgvector + MinIO.

---

## 18. Explicit non-goals for v1

- General-purpose coding agent or PR bot
- Untrusted-repo multi-tenant isolation (microVM)
- Replacing the user’s production observability stack
- Selling the product (license review for any extra graph engine)
- Neo4j or Qdrant in the platform path
- Feeding entire modules to the LLM
- Agents writing to platform Postgres except through graph-mcp / search-mcp / the worker’s own job tables

---

## 19. Naming (do not rename in code without updating this file)

**Agent:** Supervisor.

**Subagents:** Source fetcher; Secret scanner; Classifier; Stack profiler; Module partitioner; Code analysts; API extractor; Data extractor; Jobs and queues extractor; Integration and infra extractor; Subsystem synthesizer; Static path builder; Dispatch resolver; Path ranker; Run planner; Dockerfile writer; Infra provisioner; Mock generator; Config synthesizer; Build runner; Failure diagnoser; Data seeder; Tier assessor; Scenario planner; Request builder; Workflow chainer; Fuzzer; UI and event drivers; Scenario repairer; Trace collector; Claim checker; Path reconciler; Consistency critic; Coverage auditor; Gap analyst; Doc generator; Diagram generator; Simulation packager; Coverage reporter.

**Not agents:** App in sandbox; Supervisor decision; Interactive simulation UI.

**MCP:** git-mcp; fs-mcp; code-intel-mcp; graph-mcp; search-mcp; sandbox-mcp; db-mcp; http-mcp; browser-mcp; trace-mcp; mock-mcp; report-mcp; approval-mcp.

**Loops:** A build-repair; B scenario-repair; C coverage.

**Tiers (result):** full dynamic; partial dynamic; static only.

**Tiers (model):** A strongest available; B solid general; C small fast local.

---

## 20. Open decisions (only these may still change)

1. Exact Groq model IDs on the free tier (check Console at implementation time).
2. Exact Postgres schema names and indexes (semantics in section 6 are fixed; column layout is not).
3. Whether browser-mcp is required for the first sample repo (API-only sample may skip Playwright until a second sample).
4. Whether Helm / Terraform / CI extraction is complete in M2 or stubbed until M4.
5. Auth for the UI in local single-user mode (none vs simple login). Default: local single-user, no auth, bind localhost.

Everything else in this file is closed for v1.
