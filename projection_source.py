"""Provider-neutral projections with a public 2026 FantasyPros fallback."""
import asyncio
import json
import os
import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

FANTASYPROS = "https://www.fantasypros.com/nfl"
ESPN = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leaguedefaults/1"
DRAFT_SHARKS = "https://www.draftsharks.com/rankings/ppr"
POSITIONS = ("qb", "rb", "wr", "te")
ESPN_POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE"}
_CACHE = {"payload": None, "fetched_at": None}
CACHE_SECONDS = 6 * 60 * 60


def _number(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse_projection_table(html, position):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []
    rows = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all(["td", "th"])
        link = cells[0].find("a") if cells else None
        points = _number(cells[-1].get_text(" ", strip=True)) if cells else None
        if not link or points is None:
            continue
        rows.append({
            "name": link.get_text(" ", strip=True),
            "position": position.upper(),
            "projected_points": points,
        })
    return rows


def parse_adp_table(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []
    headers = [cell.get_text(" ", strip=True).upper() for cell in table.select("thead th")]
    avg_index = next((i for i, value in enumerate(headers) if value == "AVG"), None)
    rows = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td")
        link = cells[1].find("a") if len(cells) > 1 else None
        if not link:
            continue
        position_text = cells[2].get_text(" ", strip=True) if len(cells) > 2 else ""
        adp_index = avg_index if avg_index is not None and avg_index < len(cells) else len(cells) - 2
        adp = _number(cells[adp_index].get_text(" ", strip=True))
        if adp is None:
            continue
        rows.append({
            "name": link.get_text(" ", strip=True),
            "position": re.sub(r"\d", "", position_text),
            "redraft_adp": adp,
        })
    return rows


def _draft_slot_to_overall(value, teams=12):
    match = re.fullmatch(r"(\d+)\.(\d+)", str(value or "").strip())
    if not match:
        return _number(value)
    round_number, pick = map(int, match.groups())
    return float((round_number - 1) * teams + pick)


def parse_draft_sharks(html):
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        headers = [cell.get_text(" ", strip=True) for cell in table.find_all("th")]
        if "DS Proj" not in headers or "3D Value" not in headers:
            continue
        rows = []
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            player_tag = cells[1].find("player-name") if len(cells) >= 12 else None
            link = cells[1].find("a") if len(cells) >= 12 else None
            player_name = (
                " ".join(filter(None, [player_tag.get("first-name"), player_tag.get("last-name")]))
                if player_tag else link.get_text("", strip=True) if link else None
            )
            if not player_name or _number(cells[0].get_text(" ", strip=True)) is None:
                continue
            player_text = cells[1].get_text(" ", strip=True)
            position_match = re.search(r"\b(QB|RB|WR|TE)\d+\b", player_text)
            position_tag = cells[1].find("pos-roster-spot")
            rows.append({
                "name": player_name,
                "position": (
                    position_tag.get("pos-roster-spot") if position_tag
                    else position_match.group(1) if position_match else None
                ),
                "redraft_rank": int(_number(cells[0].get_text(" ", strip=True))),
                "redraft_adp": _draft_slot_to_overall(cells[3].get_text(" ", strip=True)),
                "floor_points": _number(cells[7].get_text(" ", strip=True)),
                "consensus_projected_points": _number(cells[8].get_text(" ", strip=True)),
                "projected_points": _number(cells[9].get_text(" ", strip=True)),
                "ceiling_points": _number(cells[10].get_text(" ", strip=True)),
                "redraft_value": _number(cells[11].get_text(" ", strip=True)),
                "projection_provider": "Draft Sharks 3D projections",
            })
        return rows
    return []


async def _fetch_fantasypros():
    headers = {"User-Agent": "dynasty-intelligence/0.2 (personal league analysis)"}
    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, headers=headers) as client:
        projection_responses, adp_response = await asyncio.gather(
            asyncio.gather(*[
                client.get(f"{FANTASYPROS}/projections/{position}.php?week=draft&scoring=PPR")
                for position in POSITIONS
            ]),
            client.get(f"{FANTASYPROS}/adp/ppr-overall.php"),
        )
    for response in [*projection_responses, adp_response]:
        response.raise_for_status()
    rows = []
    for position, response in zip(POSITIONS, projection_responses):
        rows.extend(parse_projection_table(response.text, position))
    adp = {row["name"].lower(): row for row in parse_adp_table(adp_response.text)}
    for row in rows:
        match = adp.get(row["name"].lower())
        if match:
            row["redraft_adp"] = match["redraft_adp"]
    return rows


async def _fetch_espn():
    fantasy_filter = {
        "players": {
            "limit": 1000,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        }
    }
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(
            ESPN, params={"view": "kona_player_info"},
            headers={
                "User-Agent": "dynasty-intelligence/0.2 (personal league analysis)",
                "x-fantasy-filter": json.dumps(fantasy_filter),
            },
        )
        response.raise_for_status()
    rows = []
    for wrapper in response.json().get("players") or []:
        player = wrapper.get("player") or {}
        position = ESPN_POSITIONS.get(player.get("defaultPositionId"))
        if not position:
            continue
        season_projection = next((
            stat for stat in player.get("stats") or []
            if stat.get("seasonId") == 2026
            and stat.get("scoringPeriodId") == 0
            and stat.get("statSourceId") == 1
            and stat.get("statSplitTypeId") == 0
        ), None)
        points = (season_projection or {}).get("appliedTotal")
        adp = (player.get("ownership") or {}).get("averageDraftPosition")
        if not isinstance(points, (int, float)) or points <= 0:
            continue
        rows.append({
            "name": player.get("fullName"), "position": position,
            "projected_points": round(float(points), 2),
            "redraft_adp": round(float(adp), 2) if isinstance(adp, (int, float)) else None,
        })
    return rows


async def _fetch_draft_sharks():
    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
        response = await client.get(
            DRAFT_SHARKS,
            headers={"User-Agent": "dynasty-intelligence/0.2 (personal league analysis)"},
        )
        response.raise_for_status()
    return parse_draft_sharks(response.text)


async def fetch_projections(force=False):
    now = datetime.now(timezone.utc)
    if (
        not force and _CACHE["payload"] is not None and _CACHE["fetched_at"] is not None
        and (now - _CACHE["fetched_at"]).total_seconds() < CACHE_SECONDS
    ):
        return {**_CACHE["payload"], "cache": {
            "status": "hit", "fetched_at": _CACHE["fetched_at"].isoformat(),
            "refresh_interval_hours": 6,
        }}
    url = os.getenv("PROJECTIONS_URL")
    try:
        if url:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
            data = payload if isinstance(payload, list) else payload.get("players", [])
            source = url
            source_type = "configured_authorized_feed"
        else:
            espn_rows, draft_sharks_rows, consensus_rows = await asyncio.gather(
                _fetch_espn(), _fetch_draft_sharks(), _fetch_fantasypros()
            )
            draft_sharks = {row["name"].lower(): row for row in draft_sharks_rows}
            consensus = {row["name"].lower(): row for row in consensus_rows}
            data = []
            merged_names = set()
            for row in espn_rows:
                ds_match = draft_sharks.get(row["name"].lower())
                fp_match = consensus.get(row["name"].lower())
                merged_names.add(row["name"].lower())
                data.append({
                    **row,
                    **(ds_match or {}),
                    **({"fantasypros_consensus_points": fp_match["projected_points"]} if fp_match else {}),
                    "projection_provider": (ds_match or {}).get("projection_provider", "ESPN 2026 PPR"),
                })
            data.extend(
                row for key, row in draft_sharks.items() if key not in merged_names
            )
            source = [DRAFT_SHARKS, ESPN, f"{FANTASYPROS}/projections/"]
            source_type = "Draft Sharks preferred; ESPN broad-coverage fallback; FantasyPros cross-check"
        payload = {
            "status": "ok", "updated_at": now.isoformat(),
            "source": source, "source_type": source_type, "data": data,
            "coverage_notes": "Season projections and PPR redraft ADP; rankings remain estimates.",
            "cache": {"status": "miss", "fetched_at": now.isoformat(), "refresh_interval_hours": 6},
        }
        _CACHE.update({"payload": payload, "fetched_at": now})
        return payload
    except Exception as exc:
        if _CACHE["payload"] is not None:
            return {**_CACHE["payload"], "cache": {
                "status": "stale_fallback", "fetched_at": _CACHE["fetched_at"].isoformat(),
                "refresh_interval_hours": 6, "refresh_error": str(exc),
            }}
        return {
            "status": "unavailable", "updated_at": now.isoformat(),
            "source": url or "FantasyPros public fallback", "error": str(exc), "data": [],
            "cache": {"status": "unavailable", "fetched_at": None, "refresh_interval_hours": 6},
        }
