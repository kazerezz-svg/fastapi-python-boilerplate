from fastapi import FastAPI, HTTPException
import asyncio
import httpx
from datetime import datetime, timezone

app = FastAPI()

LEAGUE_ID = "1337530303182290944"
BASE = "https://api.sleeper.app/v1"


async def get_json(client: httpx.AsyncClient, url: str):
    response = await client.get(url, timeout=20.0)
    response.raise_for_status()
    return response.json()


@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "Sleeper league bridge is live",
        "league_id": LEAGUE_ID,
    }


@app.get("/league-state")
async def league_state():
    try:
        async with httpx.AsyncClient() as client:
            league, users, rosters, traded_picks = await asyncio.gather(
                get_json(client, f"{BASE}/league/{LEAGUE_ID}"),
                get_json(client, f"{BASE}/league/{LEAGUE_ID}/users"),
                get_json(client, f"{BASE}/league/{LEAGUE_ID}/rosters"),
                get_json(client, f"{BASE}/league/{LEAGUE_ID}/traded_picks"),
            )

        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "league_id": LEAGUE_ID,
            "league": league,
            "users": users,
            "rosters": rosters,
            "traded_picks": traded_picks,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
