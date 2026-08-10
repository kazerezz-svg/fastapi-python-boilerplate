from fastapi import FastAPI, HTTPException
import asyncio
import httpx
from datetime import datetime, timezone, timedelta

app = FastAPI()

LEAGUE_ID = "1337530303182290944"
MY_USER_ID = "870453414893723648"  # scaceres
BASE = "https://api.sleeper.app/v1"

_player_cache = {
    "data": None,
    "fetched_at": None,
}


async def get_json(client: httpx.AsyncClient, url: str):
    response = await client.get(url, timeout=30.0)
    response.raise_for_status()
    return response.json()


async def get_players(client: httpx.AsyncClient):
    now = datetime.now(timezone.utc)

    if (
        _player_cache["data"] is not None
        and _player_cache["fetched_at"] is not None
        and now - _player_cache["fetched_at"] < timedelta(hours=24)
    ):
        return _player_cache["data"]

    players = await get_json(client, f"{BASE}/players/nfl")
    _player_cache["data"] = players
    _player_cache["fetched_at"] = now
    return players


def player_summary(player_id: str, players: dict):
    p = players.get(str(player_id), {})

    return {
        "player_id": str(player_id),
        "name": p.get("full_name") or p.get("search_full_name") or str(player_id),
        "position": p.get("position"),
        "fantasy_positions": p.get("fantasy_positions"),
        "team": p.get("team"),
        "age": p.get("age"),
        "status": p.get("status"),
        "injury_status": p.get("injury_status"),
        "years_exp": p.get("years_exp"),
    }


def user_team_name(user: dict):
    metadata = user.get("metadata") or {}
    return metadata.get("team_name") or user.get("display_name")


def build_pick_inventory(roster_id: int, traded_picks: list, seasons=(2027, 2028, 2029)):
    """
    Reconstruct current ownership of future picks.

    Every team begins with its own pick in each round.
    traded_picks contains only picks that moved.
    """
    picks = []

    traded_lookup = {}

    for pick in traded_picks:
        key = (
            int(pick["season"]),
            int(pick["round"]),
            int(pick["roster_id"]),
        )
        traded_lookup[key] = int(pick["owner_id"])

    for season in seasons:
        for original_roster_id in range(1, 13):
            for round_num in range(1, 5):
                key = (season, round_num, original_roster_id)

                current_owner = traded_lookup.get(
                    key,
                    original_roster_id
                )

                if current_owner == roster_id:
                    picks.append(
                        {
                            "season": season,
                            "round": round_num,
                            "original_roster_id": original_roster_id,
                            "is_own_pick": original_roster_id == roster_id,
                        }
                    )

    picks.sort(
        key=lambda x: (
            x["season"],
            x["round"],
            x["original_roster_id"],
        )
    )

    return picks


@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "Sleeper dynasty intelligence bridge is live",
        "league_id": LEAGUE_ID,
        "endpoints": [
            "/league-state",
            "/my-team",
        ],
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


@app.get("/my-team")
async def my_team():
    try:
        async with httpx.AsyncClient() as client:
            users, rosters, traded_picks, players = await asyncio.gather(
                get_json(client, f"{BASE}/league/{LEAGUE_ID}/users"),
                get_json(client, f"{BASE}/league/{LEAGUE_ID}/rosters"),
                get_json(client, f"{BASE}/league/{LEAGUE_ID}/traded_picks"),
                get_players(client),
            )

        user = next(
            (u for u in users if str(u.get("user_id")) == MY_USER_ID),
            None
        )

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="scaceres user not found"
            )

        roster = next(
            (
                r for r in rosters
                if str(r.get("owner_id")) == MY_USER_ID
            ),
            None
        )

        if roster is None:
            raise HTTPException(
                status_code=404,
                detail="scaceres roster not found"
            )

        roster_id = int(roster["roster_id"])

        all_player_ids = roster.get("players") or []
        starter_ids = set(roster.get("starters") or [])
        taxi_ids = set(roster.get("taxi") or [])
        reserve_ids = set(roster.get("reserve") or [])

        translated_players = []

        for player_id in all_player_ids:
            summary = player_summary(player_id, players)

            if player_id in starter_ids:
                slot = "starter"
            elif player_id in taxi_ids:
                slot = "taxi"
            elif player_id in reserve_ids:
                slot = "reserve"
            else:
                slot = "bench"

            summary["roster_slot"] = slot
            translated_players.append(summary)

        position_order = {
            "QB": 1,
            "RB": 2,
            "WR": 3,
            "TE": 4,
            "K": 5,
            "DEF": 6,
        }

        translated_players.sort(
            key=lambda x: (
                position_order.get(x.get("position"), 99),
                x.get("name") or "",
            )
        )

        picks = build_pick_inventory(
            roster_id=roster_id,
            traded_picks=traded_picks,
        )

        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "manager": {
                "user_id": user.get("user_id"),
                "username": user.get("display_name"),
                "team_name": user_team_name(user),
                "roster_id": roster_id,
            },
            "players": translated_players,
            "draft_picks": picks,
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
