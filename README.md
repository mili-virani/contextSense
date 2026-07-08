# ContextSense Monorepo

ContextSense is an AI-agent powered application with a Python FastAPI backend and a Next.js frontend.

## Directory Structure

```text
contextsense/
├── backend/          (Python, FastAPI, uv for dependency management)
│   ├── agents/       (Agent logic and orchestrators)
│   ├── mcp_clients/  (Model Context Protocol clients)
│   ├── ingestion/    (Data ingestion pipeline)
│   ├── schemas/      (Pydantic schemas)
│   ├── api/          (FastAPI routes and controllers)
│   └── tests/        (Backend unit and integration tests)
├── frontend/         (Next.js 14, App Router, TypeScript, Tailwind CSS, shadcn/ui)
├── infra/            (Docker Compose for running databases and vector stores)
│   └── docker-compose.yml
├── .env.example      (Template for project environment variables)
└── README.md         (This documentation)
```

## Prerequisites

- **Python**: `>=3.11`
- **Node.js**: `>=18` (npm or equivalent)
- **Docker & Docker Compose** (for postgres and qdrant)
- **uv**: Python package installer and resolver (`pip install uv` or equivalent)

## Getting Started

### 1. Set up Environment Variables

Copy the `.env.example` file to `.env` in the root and fill in the required API keys:

```bash
cp .env.example .env
```

### 2. Start the Infrastructure

Run the following command to start PostgreSQL and Qdrant databases:

```bash
docker compose -f infra/docker-compose.yml up -d
```

### 3. Run the Backend API

Navigate to the `backend` directory, install the dependencies, and start the development server:

```bash
cd backend
# Install dependencies
uv pip install -e .

# Start development API server
uv run uvicorn backend.main:app --reload
```

The API will be available at `http://localhost:8000`. You can access the API docs at `http://localhost:8000/docs`.

### 4. Run the Frontend

Navigate to the `frontend` directory, install dependencies, and start the Next.js development server:

```bash
cd frontend
npm install
npm run dev
```

The frontend will be available at `http://localhost:3000`.
