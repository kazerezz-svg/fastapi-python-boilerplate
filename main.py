Exit code: 0
Wall time: 1 seconds
Output:
from fastapi import FastAPI, HTTPException
import asyncio
import httpx
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
import os
from external_sources import fetch_external_context
from analysis_engine import build_external_indexes, build_league_analysis, enrich_player
from projection_source import fetch_projections
from trade_engine import search_trade_packages
from manager_behavior import build_manager_profiles

app = FastAPI()

LEAGUE_ID = os.getenv("SLEEPER_LEAGUE_ID", "1337530303182290944")
MY_USER_ID = os.getenv("SLEEPER_USER_ID", "870453414893723648")
BASE = "https://api.sleeper.app/v1"

TRANSACTION_WEEKS = range(1, 19)

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
    num_teams,
    seasons=None,
    draft_rounds=4,
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

    if seasons is None:
        current_year = datetime.now(timezone.utc).year
        seasons = range(current_year + 1, current_year + 4)

    for season in seasons:
        for original_roster_id in range(1, num_teams + 1):
            for round_num in range(1, draft_rounds + 1):
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


def build_standings_profile(roster):
    settings = roster.get("settings") or {}

    fpts = float(settings.get("fpts") or 0)
    fpts_decimal = float(settings.get("fpts_decimal") or 0) / 100

    fpts_against = float(settings.get("fpts_against") or 0)
    fpts_against_decimal = (
        float(settings.get("fpts_against_decimal") or 0) / 100
    )

    return {
        "wins": int(settings.get("wins") or 0),
        "losses": int(settings.get("losses") or 0),
        "ties": int(settings.get("ties") or 0),
        "points_for": round(fpts + fpts_decimal, 2),
        "points_against": round(
            fpts_against + fpts_against_decimal,
            2
        ),
        "total_moves": int(settings.get("total_moves") or 0),
        "waiver_budget_used":
            int(settings.get("waiver_budget_used") or 0),
    }


async def fetch_transactions(client):
    results = await asyncio.gather(
        *[
            get_json(
                client,
                f"{BASE}/league/{LEAGUE_ID}/transactions/{week}"
            )
            for week in TRANSACTION_WEEKS
        ],
        return_exceptions=True
    )

    transactions = []

    for week, result in zip(TRANSACTION_WEEKS, results):
        if isinstance(result, Exception):
            continue

        for transaction in result:
            transaction["week"] = week
            transactions.append(transaction)

    transactions.sort(
        key=lambda x: x.get("created") or 0,
        reverse=True
    )

    return transactions


async def fetch_league_chain(client, starting_league_id=LEAGUE_ID, max_seasons=10):
    """Follow Sleeper's previous_league_id links without looping forever."""
    leagues = []
    seen = set()
    league_id = str(starting_league_id)

    while league_id and league_id != "0" and league_id not in seen:
        if len(leagues) >= max_seasons:
            break
        seen.add(league_id)
        league = await get_json(client, f"{BASE}/league/{league_id}")
        leagues.append(league)
        league_id = str(league.get("previous_league_id") or "")

    return leagues


async def fetch_league_transactions(client, league):
    league_id = str(league["league_id"])
    season = str(league.get("season") or "")
    results = await asyncio.gather(
        *[
            get_json(client, f"{BASE}/league/{league_id}/transactions/{week}")
            for week in TRANSACTION_WEEKS
        ],
        return_exceptions=True,
    )
    transactions = []
    for week, result in zip(TRANSACTION_WEEKS, results):
        if isinstance(result, Exception):
            continue
        for transaction in result:
            item = dict(transaction)
            item["week"] = week
            item["league_id"] = league_id
            item["season"] = season
            transactions.append(item)
    return transactions


def translate_transaction_player_map(mapping, players):
    if not mapping:
        return []

    translated = []

    for player_id, roster_id in mapping.items():
        translated.append({
            "player_id": str(player_id),
            "player_name":
                player_summary(player_id, players)["name"],
            "roster_id": int(roster_id),
        })

    return translated


def translate_trade(
    transaction,
    players,
    roster_to_manager
):
    roster_ids = [
        int(x)
        for x in transaction.get("roster_ids") or []
    ]

    return {
        "transaction_id": transaction.get("transaction_id"),
        "created": transaction.get("created"),
        "week": transaction.get("week"),
        "rosters": [
            roster_to_manager.get(rid, {"roster_id": rid})
            for rid in roster_ids
        ],
        "adds": translate_transaction_player_map(
            transaction.get("adds"),
            players
        ),
        "drops": translate_transaction_player_map(
            transaction.get("drops"),
            players
        ),
        "draft_picks": transaction.get("draft_picks") or [],
        "waiver_budget": transaction.get("waiver_budget") or [],
    }


def build_owner_behavior(
    roster_id,
    transactions,
    roster_to_manager
):
    completed = [
        tx for tx in transactions
        if tx.get("status") == "complete"
    ]

    involved = [
        tx for tx in completed
        if roster_id in [
            int(r)
            for r in tx.get("roster_ids") or []
        ]
    ]

    trades = [
        tx for tx in involved
        if tx.get("type") == "trade"
    ]

    waivers = [
        tx for tx in involved
        if tx.get("type") == "waiver"
    ]

    free_agents = [
        tx for tx in involved
        if tx.get("type") == "free_agent"
    ]

    trade_partners = Counter()

    for tx in trades:
        for rid in tx.get("roster_ids") or []:
            rid = int(rid)

            if rid != roster_id:
                partner = roster_to_manager.get(rid, {})
                name = (
                    partner.get("username")
                    or partner.get("team_name")
                    or str(rid)
                )
                trade_partners[name] += 1

    return {
        "completed_transactions": len(involved),
        "completed_trades": len(trades),
        "waiver_claims": len(waivers),
        "free_agent_moves": len(free_agents),
        "most_common_trade_partners": [
            {
                "manager": manager,
                "trade_count": count
            }
            for manager, count
            in trade_partners.most_common(5)
        ],
    }


def estimate_pick_quality(team):
    """
    Deliberately crude pre-season heuristic.

    We are NOT pretending this is a true projection yet.
    Later we will replace/augment this with market values,
    projections and actual season Max PF.
    """
    standings = team.get("standings") or {}
    wins = standings.get("wins", 0)
    losses = standings.get("losses", 0)

    if wins + losses > 0:
        win_pct = wins / max(wins + losses, 1)

        if win_pct >= 0.67:
            return "late"
        elif win_pct <= 0.33:
            return "early"
        else:
            return "mid"

    return "unknown"


@app.get("/")
async def root():
    return {
        "status": "ok",
        "message":
            "Sleeper dynasty intelligence bridge is live",
        "league_id": LEAGUE_ID,
        "endpoints": [
            "/league-state",
            "/my-team",
            "/league-map",
            "/transactions",
            "/trades",
            "/history",
            "/external-context",
            "/analysis/league",
            "/analysis/player/{player_id}",
            "/trade-search/{target_player_id}",
            "/manager-behavior",
        ],
    }


@app.get("/league-state")
async def league_state():
    try:
        async with httpx.AsyncClient() as client:
            league, users, rosters, traded_picks = (
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
                )
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
            (
                league,
                users,
                rosters,
                traded_picks,
                players,
                transactions,
            ) = await asyncio.gather(
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
                fetch_transactions(client),
            )

        num_teams = int(
            league.get("total_rosters")
            or league.get("settings", {}).get("num_teams")
            or 12
        )
        league_season = int(league.get("season") or datetime.now(timezone.utc).year)
        draft_rounds = int(league.get("settings", {}).get("draft_rounds") or 4)
        future_seasons = range(league_season + 1, league_season + 4)

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
                seasons=future_seasons,
                draft_rounds=draft_rounds,
            )

            roster_profile = calculate_roster_profile(
                translated_players
            )

            standings = build_standings_profile(
                roster
            )

            owner_behavior = build_owner_behavior(
                roster_id,
                transactions,
                roster_to_manager
            )

            teams.append({
                "roster_id": roster_id,
                "manager": manager,
                "is_my_team":
                    str(manager.get("user_id")) == MY_USER_ID,
                "players": translated_players,
                "draft_picks": picks,
                "roster_profile": roster_profile,
                "standings": standings,
                "owner_behavior": owner_behavior,
            })

        for team in teams:
            team["pick_quality_estimate"] = (
                estimate_pick_quality(team)
            )

        teams.sort(
            key=lambda x: x["roster_id"]
        )

        return {
            "updated_at":
                datetime.now(timezone.utc).isoformat(),
            "league_id": LEAGUE_ID,
            "league_name": league.get("name"),
            "num_teams": num_teams,
            "data_provenance": {
                "league_state": "measured_live_sleeper_api",
                "player_metadata": "measured_sleeper_player_catalog",
                "pick_quality_estimate": "heuristic_in_season_record_only",
            },
            "teams": teams,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@app.get("/my-team")
async def my_team():
    data = await league_map()

    my_team_data = next(
        (
            team
            for team in data["teams"]
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
        "updated_at": data["updated_at"],
        **my_team_data,
    }


@app.get("/transactions")
async def transactions_endpoint():
    try:
        async with httpx.AsyncClient() as client:
            users, rosters, players, transactions = (
                await asyncio.gather(
                    get_json(
                        client,
                        f"{BASE}/league/{LEAGUE_ID}/users"
                    ),
                    get_json(
                        client,
                        f"{BASE}/league/{LEAGUE_ID}/rosters"
                    ),
                    get_players(client),
                    fetch_transactions(client),
                )
            )

        _, roster_to_manager = build_roster_maps(
            users,
            rosters
        )

        output = []

        for tx in transactions:
            roster_ids = [
                int(r)
                for r in tx.get("roster_ids") or []
            ]

            output.append({
                "transaction_id":
                    tx.get("transaction_id"),
                "type": tx.get("type"),
                "status": tx.get("status"),
                "created": tx.get("created"),
                "week": tx.get("week"),
                "managers": [
                    roster_to_manager.get(
                        rid,
                        {"roster_id": rid}
                    )
                    for rid in roster_ids
                ],
                "adds":
                    translate_transaction_player_map(
                        tx.get("adds"),
                        players
                    ),
                "drops":
                    translate_transaction_player_map(
                        tx.get("drops"),
                        players
                    ),
                "draft_picks":
                    tx.get("draft_picks") or [],
            })

        return {
            "updated_at":
                datetime.now(timezone.utc).isoformat(),
            "transactions": output,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@app.get("/trades")
async def trades_endpoint():
    try:
        async with httpx.AsyncClient() as client:
            users, rosters, players, transactions = (
                await asyncio.gather(
                    get_json(
                        client,
                        f"{BASE}/league/{LEAGUE_ID}/users"
                    ),
                    get_json(
                        client,
                        f"{BASE}/league/{LEAGUE_ID}/rosters"
                    ),
                    get_players(client),
                    fetch_transactions(client),
                )
            )

        _, roster_to_manager = build_roster_maps(
            users,
            rosters
        )

        trades = [
            translate_trade(
                tx,
                players,
                roster_to_manager
            )
            for tx in transactions
            if (
                tx.get("type") == "trade"
                and tx.get("status") == "complete"
            )
        ]

        return {
            "updated_at":
                datetime.now(timezone.utc).isoformat(),
            "trade_count": len(trades),
            "trades": trades,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@app.get("/history")
async def history_endpoint():
    """Normalized completed transaction history across linked Sleeper seasons."""
    try:
        async with httpx.AsyncClient() as client:
            leagues = await fetch_league_chain(client)
            players = await get_players(client)
            season_payloads = await asyncio.gather(
                *[
                    asyncio.gather(
                        get_json(client, f"{BASE}/league/{league['league_id']}/users"),
                        get_json(client, f"{BASE}/league/{league['league_id']}/rosters"),
                        fetch_league_transactions(client, league),
                    )
                    for league in leagues
                ]
            )

        output = []
        season_counts = {}
        for league, (users, rosters, transactions) in zip(leagues, season_payloads):
            _, roster_to_manager = build_roster_maps(users, rosters)
            completed = [tx for tx in transactions if tx.get("status") == "complete"]
            season = str(league.get("season") or "")
            season_counts[season] = len(completed)
            for tx in completed:
                roster_ids = [int(r) for r in tx.get("roster_ids") or []]
                output.append({
                    "transaction_id": tx.get("transaction_id"),
                    "league_id": tx.get("league_id"),
                    "season": season,
                    "week": tx.get("week"),
                    "created": tx.get("created"),
                    "type": tx.get("type"),
                    "managers": [
                        roster_to_manager.get(rid, {"roster_id": rid})
                        for rid in roster_ids
                    ],
                    "adds": translate_transaction_player_map(tx.get("adds"), players),
                    "drops": translate_transaction_player_map(tx.get("drops"), players),
                    "draft_picks": tx.get("draft_picks") or [],
                    "waiver_budget": tx.get("waiver_budget") or [],
                })

        output.sort(key=lambda tx: tx.get("created") or 0, reverse=True)
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "league_chain": [
                {"league_id": league.get("league_id"), "season": league.get("season")}
                for league in leagues
            ],
            "season_counts": season_counts,
            "transaction_count": len(output),
            "transactions": output,
            "data_provenance": "measured_linked_sleeper_leagues",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/external-context")
async def external_context_endpoint():
    return await fetch_external_context()


@app.get("/analysis/league")
async def league_analysis_endpoint():
    league, context, projections = await asyncio.gather(
        league_map(), fetch_external_context(), fetch_projections()
    )
    return build_league_analysis(league, context, projections)


@app.get("/analysis/player/{player_id}")
async def player_analysis_endpoint(player_id: str):
    league, context = await asyncio.gather(league_map(), fetch_external_context())
    indexes = build_external_indexes(context)
    for team in league.get("teams") or []:
        for player in team.get("players") or []:
            if str(player.get("player_id")) == str(player_id):
                return {
                    "updated_at": league.get("updated_at"),
                    "owner": team.get("manager"),
                    "roster_id": team.get("roster_id"),
                    "player": enrich_player(player, indexes),
                }
    raise HTTPException(status_code=404, detail="player not found in league")


@app.get("/trade-search/{target_player_id}")
async def trade_search_endpoint(target_player_id: str, buyer_roster_id: int | None = None):
    league, context, projections, history = await asyncio.gather(
        league_map(), fetch_external_context(), fetch_projections(), history_endpoint()
    )
    analysis = build_league_analysis(league, context, projections)
    if buyer_roster_id is None:
        my_team = next((team for team in analysis["teams"] if team.get("is_my_team")), None)
        if not my_team:
            raise HTTPException(status_code=404, detail="configured user roster not found")
        buyer_roster_id = my_team["roster_id"]
    ktc_index = build_external_indexes(context)["ktc"]
    profiles = build_manager_profiles(history, ktc_index)
    try:
        return search_trade_packages(
            analysis, target_player_id, buyer_roster_id, ktc_index, profiles
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/manager-behavior")
async def manager_behavior_endpoint():
    history, context = await asyncio.gather(history_endpoint(), fetch_external_context())
    return {
        "updated_at": history.get("updated_at"),
        "profiles": build_manager_profiles(
            history, build_external_indexes(context)["ktc"]
        ),
    }

