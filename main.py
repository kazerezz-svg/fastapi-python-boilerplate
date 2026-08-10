from fastapi import FastAPI, HTTPException
import asyncio
import httpx
from datetime import datetime, timezone, timedelta
from collections import defaultdict

app = FastAPI()

LEAGUE_ID = "1337530303182290944"
MY_USER_ID = "870453414893723648"  # scaceres
BASE = "https://api.sleeper.app/v1"

FUTURE_SEASONS = (2027, 2028, 2029)

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


def user_team_name(user: dict):
    metadata = user.get("metadata") or {}
    return metadata.get("team_name") or user.get("display_name")


def player_summary(player_id: str, players: dict):
    p = players.get(str(player_id), {})

    return {
        "player_id": str(player_id),
        "name": p.get("full_name") or str(player_id),
        "position": p.get("position"),
        "team": p.get("team"),
        "age": p.get("age"),
        "status": p.get("status"),
        "injury_status": p.get("injury_status"),
        "years_exp": p.get("years_exp"),
    }


def build_roster_maps(users, rosters):
    user_by_id = {
        str(u["user_id"]): u
        for u in users
    }

    roster_to_manager = {}

    for roster in rosters:
        roster_id = int(roster["roster_id"])
        owner_id = str(roster.get("owner_id"))

        user = user_by_id.get(owner_id, {})

        roster_to_manager[roster_id] = {
            "roster_id": roster_id,
            "user_id": owner_id,
            "username": user.get("display_name"),
            "team_name": user_team_name(user) if user else None,
        }

    return user_by_id, roster_to_manager


def build_pick_ownership(
    target_roster_id,
    traded_picks,
    roster_to_manager,
    num_teams
):
    traded_lookup = {}

    for pick in traded_picks:
        key = (
            int(pick["season"]),
            int(pick["round"]),
            int(pick["roster_id"]),
        )

        traded_lookup[key] = int(pick["owner_id"])

    picks = []

    for season in FUTURE_SEASONS:
        for original_roster_id in range(1, num_teams + 1):
            for round_num in range(1, 5):

                key = (
                    season,
                    round_num,
                    original_roster_id
                )

                current_owner = traded_lookup.get(
                    key,
                    original_roster_id
                )

                if current_owner != target_roster_id:
                    continue

                original_manager = roster_to_manager.get(
                    original_roster_id,
                    {}
                )

                picks.append({
                    "season": season,
                    "round": round_num,
                    "original_roster_id": original_roster_id,
                    "original_owner_username":
                        original_manager.get("username"),
                    "original_owner_team":
                        original_manager.get("team_name"),
                    "is_own_pick":
                        original_roster_id == target_roster_id,
                })

    picks.sort(
        key=lambda x: (
            x["season"],
            x["round"],
            x["original_roster_id"],
        )
    )

    return picks


def translate_roster(roster, players):
    starter_ids = set(roster.get("starters") or [])
    taxi_ids = set(roster.get("taxi") or [])
    reserve_ids = set(roster.get("reserve") or [])

    output = []

    for player_id in roster.get("players") or []:
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
        output.append(summary)

    position_order = {
        "QB": 1,
        "RB": 2,
        "WR": 3,
        "TE": 4,
    }

    output.sort(
        key=lambda x: (
            position_order.get(x.get("position"), 99),
            x.get("roster_slot") != "starter",
            x.get("name") or "",
        )
    )

    return output


def calculate_roster_profile(translated_players):
    by_position = defaultdict(list)

    for player in translated_players:
        pos = player.get("position")

        if pos in ("QB", "RB", "WR", "TE"):
            by_position[pos].append(player)

    profile = {}

    for position in ("QB", "RB", "WR", "TE"):
        group = by_position[position]

        ages = [
            p["age"]
            for p in group
            if isinstance(p.get("age"), (int, float))
        ]

        starters = [
            p for p in group
            if p.get("roster_slot") == "starter"
        ]

        young_players = [
            p for p in group
            if isinstance(p.get("age"), (int, float))
            and p["age"] <= 24
        ]

        profile[position] = {
            "count": len(group),
            "starter_count": len(starters),
            "average_age":
                round(sum(ages) / len(ages), 2)
                if ages else None,
            "age_24_or_younger": len(young_players),
        }

    all_ages = [
        p["age"]
        for p in translated_players
        if isinstance(p.get("age"), (int, float))
        and p.get("position") in ("QB", "RB", "WR", "TE")
    ]

    profile["overall"] = {
        "average_age":
            round(sum(all_ages) / len(all_ages), 2)
            if all_ages else None,
        "player_count": len(all_ages),
    }

    return profile


@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "Sleeper dynasty intelligence bridge is live",
        "league_id": LEAGUE_ID,
        "endpoints": [
            "/league-state",
            "/my-team",
            "/league-map",
        ],
    }


@app.get("/league-state")
async def league_state():
    try:
        async with httpx.AsyncClient() as client:
            league, users, rosters, traded_picks = await asyncio.gather(
                get_json(
                    client,
                    f"{BASE}/league/{LEAGUE_ID}"
                ),
                get_json(
                    client,
                    f"{BASE}/league/{LEAGUE_ID}/users"
                ),
                get_json(
                    client,
                    f"{BASE}/league/{LEAGUE_ID}/rosters"
                ),
                get_json(
                    client,
                    f"{BASE}/league/{LEAGUE_ID}/traded_picks"
                ),
            )

        return {
            "updated_at":
                datetime.now(timezone.utc).isoformat(),
            "league_id": LEAGUE_ID,
            "league": league,
            "users": users,
            "rosters": rosters,
            "traded_picks": traded_picks,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@app.get("/league-map")
async def league_map():
    try:
        async with httpx.AsyncClient() as client:
            league, users, rosters, traded_picks, players = (
                await asyncio.gather(
                    get_json(
                        client,
                        f"{BASE}/league/{LEAGUE_ID}"
                    ),
                    get_json(
                        client,
                        f"{BASE}/league/{LEAGUE_ID}/users"
                    ),
                    get_json(
                        client,
                        f"{BASE}/league/{LEAGUE_ID}/rosters"
                    ),
                    get_json(
                        client,
                        f"{BASE}/league/{LEAGUE_ID}/traded_picks"
                    ),
                    get_players(client),
                )
            )

        num_teams = int(
            league.get("total_rosters")
            or league.get("settings", {}).get("num_teams")
            or 12
        )

        _, roster_to_manager = build_roster_maps(
            users,
            rosters
        )

        teams = []

        for roster in rosters:
            roster_id = int(roster["roster_id"])

            manager = roster_to_manager.get(
                roster_id,
                {}
            )

            translated_players = translate_roster(
                roster,
                players
            )

            picks = build_pick_ownership(
                target_roster_id=roster_id,
                traded_picks=traded_picks,
                roster_to_manager=roster_to_manager,
                num_teams=num_teams,
            )

            roster_profile = calculate_roster_profile(
                translated_players
            )

            teams.append({
                "roster_id": roster_id,
                "manager": manager,
                "is_my_team":
                    str(manager.get("user_id")) == MY_USER_ID,
                "players": translated_players,
                "draft_picks": picks,
                "roster_profile": roster_profile,
            })

        teams.sort(
            key=lambda x: x["roster_id"]
        )

        return {
            "updated_at":
                datetime.now(timezone.utc).isoformat(),
            "league_id": LEAGUE_ID,
            "league_name": league.get("name"),
            "num_teams": num_teams,
            "teams": teams,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@app.get("/my-team")
async def my_team():
    try:
        league_map_data = await league_map()

        my_team_data = next(
            (
                team
                for team in league_map_data["teams"]
                if team["is_my_team"]
            ),
            None
        )

        if my_team_data is None:
            raise HTTPException(
                status_code=404,
                detail="scaceres roster not found"
            )

        return {
            "updated_at":
                league_map_data["updated_at"],
            **my_team_data,
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
