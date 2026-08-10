Exit code: 0
Wall time: 1.1 seconds
Output:
"""Optional, provider-neutral projected-points input."""
import os
from datetime import datetime, timezone

import httpx


async def fetch_projections():
    url = os.getenv("PROJECTIONS_URL")
    if not url:
        return {
            "status": "not_configured",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": None,
            "data": [],
            "required_schema": {
                "player_id": "Sleeper player ID (preferred)",
                "name": "player name fallback",
                "projected_points": "full regular-season points",
            },
        }
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        data = payload if isinstance(payload, list) else payload.get("players", [])
        return {
            "status": "ok",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": url,
            "data": data,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": url,
            "error": str(exc),
            "data": [],
        }

