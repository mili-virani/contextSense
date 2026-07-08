import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncpg

# Load dotenv configuration from workspace root
workspace_root = Path(__file__).resolve().parent.parent
env_path = workspace_root / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

# Ensure workspace root is in sys.path
if str(workspace_root) not in sys.path:
    sys.path.append(str(workspace_root))

from backend.api import routes

@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    app.state.db_pool = await asyncpg.create_pool(
        database_url,
        statement_cache_size=0,
        min_size=1,
        max_size=10
    )
    yield
    await app.state.db_pool.close()

app = FastAPI(title="ContextSense API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to ContextSense API"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

