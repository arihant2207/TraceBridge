# TraceBridge

TraceBridge is a deterministic engineering-evidence validation engine for safety and requirements compliance. It processes requirements, test execution records, and timeseries sensor telemetry to verify traceability and evaluate measurement thresholds against recorded data. The engine applies 12 deterministic rules, calculates an evidence quality score, and evaluates a separate gate status. It operates entirely as pure Python logic with no probabilistic or language-model components.

## Stack

- **Backend**: Python 3.13, FastAPI, Pandas, Pydantic, SQLite, pytest
- **Frontend**: Next.js 14 (App Router), React 18, TypeScript, Vanilla CSS
- **Code Generation**: `openapi-typescript` for automated schema-to-client type generation

## Prerequisites

Observed on this workstation:
- **Python**: 3.13.1
- **Node.js**: v22.18.0
- **npm**: 10.9.2

## Setup and Running

### 1. Backend Setup

From the repository root:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Run the FastAPI backend server:

```bash
uvicorn app.main:app --port 8000
```

The interactive API documentation is accessible at `http://localhost:8000/docs`.

### 2. Frontend Setup

In a separate terminal, from the repository root:

```bash
cd frontend
npm install
```

Generate typed API definitions from the running backend (if schema changes):

```bash
npm run gen:types
```

Start the frontend development server:

```bash
npm run dev
```

The web application is accessible at `http://localhost:3000`. Next.js proxies `/api/v1/*` requests directly to `http://localhost:8000/api/v1/*`.

To build the frontend for production:

```bash
npm run build
```

### 3. Running Automated Tests

Run the backend pytest test suite from the `backend/` directory:

```bash
cd backend
pytest -v
```

During this session, `pytest -v` executed 131 tests with 131 passing:
```
====================== 131 passed, 13 warnings in 3.66s =======================
```

To run frontend type checking:

```bash
cd frontend
npx tsc --noEmit
```

## Project Structure

```
TraceBridge/
├── README.md
├── docs/
│   ├── SPEC.md             # Frozen specification v1.0 (source of truth)
│   ├── rules.md            # Rule definitions (R01–R12), evaluation pipeline, scoring
│   ├── limitations.md      # Known limitations and engineering boundaries
│   └── qa-checklist.md     # Manual verification checklist
├── backend/
│   ├── requirements.txt    # Pinned Python dependencies
│   ├── pytest.ini          # Pytest path and runner configuration
│   ├── app/
│   │   ├── main.py         # FastAPI application entry point and error handlers
│   │   ├── service.py      # Orchestrator tying loader, engine, and repository
│   │   ├── api/            # API routing and Pydantic schemas
│   │   │   ├── routes.py
│   │   │   └── schemas.py
│   │   ├── ingestion/      # CSV schema validation (SCH-001..SCH-007) and loader
│   │   │   └── loader.py
│   │   ├── engine/         # Pure validation functions and models
│   │   │   ├── models.py
│   │   │   ├── rules.py
│   │   │   ├── evaluate.py
│   │   │   ├── scoring.py
│   │   │   └── ruleset.json
│   │   ├── db/             # SQLite database layer and repository
│   │   │   ├── database.py
│   │   │   └── repo.py
│   │   └── reporting/      # Markdown, JSON, and CSV export generators
│   │       └── exports.py
│   ├── samples/            # Clean and fault fixture datasets
│   │   ├── clean/
│   │   ├── fault/
│   │   ├── expected_clean.json
│   │   └── expected_fault.json
│   └── tests/              # Automated test suites
└── frontend/
    ├── package.json
    ├── tsconfig.json
    ├── next.config.mjs     # API proxy rewrites
    ├── types/              # Generated TypeScript API schemas
    ├── lib/                # Typed API client wrapper
    ├── components/         # Shared UI components
    └── app/                # Next.js App Router pages
```

## What the Score and Gate Mean

TraceBridge outputs two distinct and decoupled verification metrics:

1. **Quality Score (0.0 to 100.0)**:
   Measures evidence consistency across the 11 scored checks (R01–R08, R10–R12; R09 excluded). It represents the unweighted arithmetic mean of entity pass rates.
   - The score measures **evidence quality only**; it is not a safety, correctness, or certification result.
   - A high score **never overrides a blocked gate**.

2. **Gate Status (`BLOCKED_CRITICAL`, `BLOCKED_HIGH`, `NOT_BLOCKED`)**:
   Enforces strict evidence completeness and non-contradiction:
   - `BLOCKED_CRITICAL`: Raised if any non-OBSERVATION Critical finding exists (e.g. status vs measurement contradiction R10).
   - `BLOCKED_HIGH`: Raised if any non-OBSERVATION High finding exists or if any test evaluation is `INCONCLUSIVE`.
   - `NOT_BLOCKED`: Assigned only when zero blocking findings and zero inconclusive evaluations exist.
   - **`NOT_BLOCKED` is not an approval**: It indicates absence of blocking defects within the recorded evidence, not system certification.
