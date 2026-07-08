# ContextSense Backend

FastAPI Python backend for ContextSense, using `uv` for dependency management.

## Setup

Ensure you have `uv` installed. Run:

```bash
uv pip install -e .
```

## Running the API

To start the API in development mode:

```bash
uv run uvicorn backend.main:app --reload
```

## Testing

To run backend tests:

```bash
uv run pytest
```
