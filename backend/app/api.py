"""
Application-level API routes.

Expose `/live` for Render and other load balancers.
"""

from fastapi import APIRouter

# No version prefix; live endpoint is exactly `/live`
router = APIRouter()


@router.get("/live")
async def live():
    """Liveness probe used by Render (and other health checks)."""
    return {"status": "ok"}



