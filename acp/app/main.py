"""Single ACP process: mounted MCP surface plus separate Razorpay REST webhook."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import close_db, init_db
from .mcp_server import asgi_app as mcp_asgi_app, mcp
from .payments.webhook_handler import router as webhook_router

mcp_app = mcp_asgi_app()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    # A mounted FastMCP app does not receive its child lifespan from FastAPI;
    # explicitly run the SDK's session manager around the parent app lifetime.
    async with mcp.session_manager.run():
        yield
    await close_db()


app = FastAPI(title="RZR-Handshake ACP", version="1.0.0", lifespan=lifespan)
app.mount("/mcp", mcp_app)
app.include_router(webhook_router)


@app.middleware("http")
async def normalize_mcp_root(request, call_next):
    """Avoid a POST 307 redirect for clients configured with ``/mcp``."""
    if request.scope.get("path") == "/mcp":
        request.scope["path"] = "/mcp/"
        request.scope["raw_path"] = b"/mcp/"
    return await call_next(request)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "acp"}
