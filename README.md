# Autonomous Software Incident Investigator (ASII)

ASII is a demonstration project for investigating software incidents. Its
current implementation collects deterministic evidence by connecting an
incident report to relevant application source lines, Git history, commit
diffs, and function boundaries. It does **not** autonomously determine or
confirm a root cause.

## Current implementation

The application is a FastAPI demo with simulated database and payment
failures. The investigation workflow is:

1. A failure endpoint writes a structured error log event. Each HTTP request
   uses the supplied `X-Request-ID` header or receives a generated UUID.
2. The investigation request is searched against Python files under `app/`.
   Failure type and message keywords are weighted more heavily than endpoint
   keywords. Matching lines include nearby source context and function
   metadata extracted with Python's AST parser; source is not executed.
3. For each matching file, the pipeline retrieves recent Git history and ranks
   commits using deterministic keyword, source-relevance, and recency scores.
4. For potentially relevant commits, it retrieves the Git diff, parses added
   and deleted lines, and looks up function boundaries from the historical
   commit. Deleted lines are correlated against the parent commit's function
   boundaries. These are supporting correlations, not proof of causality.
5. The pipeline builds and validates a structured investigation report using
   the Pydantic schema, and the API returns that report.

Source evidence is drawn from the current working tree. Comparisons between
changed lines and source evidence are reported as available only when the
investigated commit is `HEAD` and the working-tree file matches `HEAD`.

## API

FastAPI's interactive API documentation is available at `/docs` when the
application is running.

| Method and path | Purpose |
| --- | --- |
| `GET /` | Returns a demo application welcome response. |
| `GET /health` | Returns a basic service health response. |
| `GET /simulate-failure?failure_type=database` | Logs a simulated database failure and returns HTTP 503. |
| `GET /simulate-failure?failure_type=payment` | Logs a simulated payment failure and returns HTTP 502. |
| `GET /incidents/recent?limit=20` | Returns recent logged error events; the API accepts limits from 1 to 100. |
| `GET /incidents/summary` | Summarizes up to 100 logged error events by incident type. |
| `POST /investigations/run` | Runs the deterministic investigation workflow for the supplied incident. |

The investigation request body is:

```json
{
  "failure_type": "database",
  "message": "Database connection failed",
  "endpoint": "/simulate-failure"
}
```

The request fields are required and length-limited by the API model. The
simulated failure endpoint accepts only `database` and `payment`.

## Logging and request IDs

Application logs are JSON-formatted and written to both the console and
`logs/app.log`. The JSON events include a UTC timestamp, level, service,
logger, request ID, and message. When present, endpoint, failure type, and
status code are also included. Malformed or non-JSON log lines are skipped by
the log collector.

The HTTP middleware uses the caller's `X-Request-ID` value when provided;
otherwise it generates a UUID. The ID is stored in request context for log
formatting and is returned in the `X-Request-ID` response header.

## Investigation report

The response is validated as an `InvestigationReport` and contains:

- `incident`: the submitted incident fields.
- `investigation_status`: `evidence_found` or `no_source_evidence`.
- `source_evidence`: matching file, line number, keywords, raw integer
  relevance score, code snippet, context, and function metadata (which may be
  `null`).
- `git_history`: commit records grouped by investigated file.
- `potentially_relevant_commits`: commits with matching keywords, component
  scores, overall relevance score, and `change_evidence`.
- `statistics`: source matches, files investigated, history commits found,
  and potentially relevant commits.
- `diagnosis`: a `root_cause_confirmed` boolean and explanatory message. The
  current deterministic pipeline sets the boolean to `false`.

Change evidence retains added and deleted lines with their respective new-
and old-file line numbers, historical function matches, and separate diff
and historical AST statuses. Source overlap is only interpreted when its
status is `available`. Unavailable or invalid evidence is represented by
statuses and optional error details rather than being treated as confirmation.

## Setup

Requirements: Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), and Git
available for repository history and diff analysis.

From the project directory:

```sh
uv sync --dev
```

## Run the application

```sh
uv run uvicorn app.main:app --reload
```

By default, Uvicorn serves the application at `http://127.0.0.1:8000`.

## Run tests

Run the complete test suite:

```sh
uv run python -m pytest -v
```

Run tests with coverage:

```sh
uv run python -m pytest --cov=app --cov-report=term-missing
```

The tests cover the API, logging and investigation workflow, source and AST
analysis, Git history and diffs, historical source analysis, and report
validation.

## Security boundaries and limitations

- Source search is restricted to Python files under `app/`. It rejects
  symlinked files and does not traverse symlinked directories; candidate
  paths are resolved and checked against the resolved source directory.
- Git history, diff, and historical source operations are read-only and
  restricted to Python paths under `app/`. Historical source is read from
  Git objects without checking out or executing it. Python files are parsed
  with `ast`.
- The current API has no authentication or authorization. The simulated
  incident and log endpoints are for local demonstration, not an indication
  of production readiness. Protect access and logs before deploying in a
  sensitive environment.
- Result limits are capped (50 source results, 50 commits per file, and 100
  returned log events). These caps do not bound the amount of source tree or
  log data scanned, nor do they impose a Git diff patch-size limit.
- Keyword matching and score-based ranking are heuristics. The report
  presents evidence and potential relevance; it does not establish root
  cause.

## Planned, not implemented

Future Agentic AI work may build on the deterministic evidence-gathering
workflow. LangGraph orchestration, LLM reasoning, autonomous root-cause
diagnosis, automatic patch generation, source-code execution, and GitHub pull
request creation are **not implemented** in this project version.