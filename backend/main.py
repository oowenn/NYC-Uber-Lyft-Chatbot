"""
NYC Ridehail Analytics Chatbot - FastAPI Backend
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import time

from api.chat import router as chat_router
from api.health import router as health_router
from api.quota import router as quota_router
from api.data_preview import router as data_preview_router
from middleware.turnstile import TurnstileMiddleware
from middleware.rate_limit import RateLimitMiddleware
from middleware.circuit_breaker import CircuitBreakerMiddleware
from db.duckdb_setup import init_duckdb, close_duckdb

# Load env files explicitly so local dev works whether vars are in
# backend/.env (legacy/local) or root .env (docker/demo).
# Root .env should win for interview/demo runs.
backend_dir = Path(__file__).resolve().parent
load_dotenv(backend_dir / ".env", override=False)
load_dotenv(backend_dir.parent / ".env", override=True)

# Global state
duckdb_conn = None
circuit_breaker = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources"""
    global duckdb_conn, circuit_breaker
    
    # Initialize DuckDB
    duckdb_conn = init_duckdb()
    app.state.duckdb = duckdb_conn

    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    if provider == "openai":
        model = os.getenv("OPENAI_MODEL", "gpt-5-nano")
    elif provider == "groq":
        model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    else:
        model = os.getenv("OLLAMA_MODEL", "llama3:latest")
    timeout = os.getenv("LLM_TIMEOUT", "300")
    print(f"LLM config -> provider={provider}, model={model}, timeout={timeout}s")
    
    # Initialize circuit breaker
    from middleware.circuit_breaker import CircuitBreaker
    circuit_breaker = CircuitBreaker()
    app.state.circuit_breaker = circuit_breaker
    
    yield
    
    # Cleanup
    if duckdb_conn:
        close_duckdb(duckdb_conn)


app = FastAPI(
    title="NYC Ridehail Analytics Chatbot API",
    description="API for querying NYC TLC FHVHV data",
    version="1.0.0",
    lifespan=lifespan
)

# CORS - configurable for production
cors_origins_str = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
cors_origins = [origin.strip() for origin in cors_origins_str.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware order matters: Turnstile -> Rate Limit -> Circuit Breaker
app.add_middleware(TurnstileMiddleware)
app.add_middleware(RateLimitMiddleware, 
                   per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "5")),
                   per_day=int(os.getenv("RATE_LIMIT_PER_DAY", "50")),
                   global_cap=int(os.getenv("GLOBAL_DAILY_CAP", "1000")))
app.add_middleware(CircuitBreakerMiddleware)

# Routers
app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(quota_router, prefix="/api", tags=["quota"])
app.include_router(data_preview_router, prefix="/api", tags=["data"])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    # Pass through HTTPException so FastAPI can return proper status/detail
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    
    # Log full exception server-side for debugging
    import traceback
    print("Unhandled exception in request:", repr(exc))
    traceback.print_exc()
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc) if os.getenv("DEBUG") == "true" else "An error occurred",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", 8000)))

