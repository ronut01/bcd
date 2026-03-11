# bcd

`bcd` is an open-source personalized decision prediction system. It predicts which option a specific user is most likely to choose based on profile signals, prior decisions, current context, and feedback-driven memory updates.

## Why this project exists

Most ranking systems try to predict what is globally correct, popular, or optimal.

`bcd` models something different:

> Given these options, what would this specific user most likely choose right now?

This repository is intentionally built as a research-friendly MVP:

- local-first and reproducible
- easy to inspect and extend
- modular enough for future retrieval, LLM, and agent experiments
- simple enough to run without external services

## MVP features

- sample user profile initialization
- decision request input with 2-5 candidate options
- optional structured context
- relevant memory and history retrieval
- predicted choice with confidence and explanation
- actual choice feedback logging
- memory and preference snapshot updates
- local API, CLI demo, and evaluation script

## Tech stack

- Python 3.11+
- FastAPI
- SQLModel + SQLite
- Typer CLI
- pytest

## Quickstart

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Initialize the sample user and seed history

```bash
python scripts/init_sample_data.py
```

### 3. Run the API

```bash
uvicorn bcd.api.app:app --reload
```

### 4. Try the local CLI demo

```bash
python scripts/run_demo.py
```

### 5. Run the baseline evaluation

```bash
python scripts/evaluate_baseline.py
```

## Core API endpoints

- `POST /profiles/bootstrap-sample`
- `GET /profiles/{user_id}`
- `POST /decisions/predict`
- `POST /decisions/{request_id}/feedback`
- `GET /users/{user_id}/history`
- `GET /users/{user_id}/memories`

## Repository layout

```text
bcd/
├─ README.md
├─ LICENSE
├─ docs/
├─ data/
├─ demo/
├─ scripts/
├─ src/bcd/
└─ tests/
```

See [`docs/architecture.md`](docs/architecture.md), [`docs/data_model.md`](docs/data_model.md), and [`docs/evaluation.md`](docs/evaluation.md) for details.
