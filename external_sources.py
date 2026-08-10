Exit code: 0
Wall time: 1.1 seconds
Output:
"""Public-source adapters. Parsers are separate from network access for testing."""
import json
import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

KTC_URL = "https://keeptradecut.com/dynasty-rankings"
OL_URL = "https://www.4for4.com/2026/preseason/2026-projected-offensive-line-rankings"
SOS_URLS = {
    "weeks_1_13": "https://fftoolbox.fulltimefantasy.com/football/strength_of_schedule.cfm?type=a",
    "weeks_1_17": "https://fftoolbox.fulltimefantasy.com/football/strength_of_schedule.cfm?type=e",
}
HEADERS = {"User-Agent": "dynasty-intelligence/0.1 (+public fantasy data adapter)"}


def parse_ktc(html: str, superflex: bool = True) -> list[dict]:
    match = re.search(r"var playersArray = (\[.*?\]);", html, re.DOTALL)
    if not match:
        raise ValueError("KTC playersArray was not present")
    players = json.loads(match.group(1))
    key = "superflexValues" if superflex else "oneQBValues"
    output = []
    for player in players:
        values = player.get(key) or {}
        output.append({
            "name": player.get("playerName"),
            "position": player.get("position"),
            "team": player.get("team"),
            "age": player.get("age"),
            "value": values.get("value"),
            "rank": values.get("rank"),
            "positional_rank": values.get("positionalRank"),
            "tier": values.get("overallTier"),
        })
    return output


def _table_rows(html: str, required_headers: set[str]) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        headers = [
            re.sub(r"[^A-Za-z]+$", "", cell.get_text(" ", strip=True))
            for cell in table.find_all("th")
        ]
        if not required_headers.issubset(set(headers)):
            continue
        rows = []
        for row in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
            if len(cells) >= len(headers):
                rows.append(dict(zip(headers, cells)))
        return rows
    raise ValueError(f"table not found: {sorted(required_headers)}")


def _number(value):
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    return float(match.group()) if match else None


def parse_offensive_lines(html: str) -> list[dict]:
    match = re.search(r"var D=\[(.*?)\];", html, re.DOTALL)
    if match:
        rows = re.findall(
            r'\[\s*(\d+),\s*"([A-Z]+)",\s*([\d.]+),\s*(\d+),'
            r'\s*([\d.]+),\s*(\d+),\s*([\d.]+),\s*(\d+)\s*\]',
            match.group(1),
        )
        return [{
            "team": team, "run_grade": float(run_grade), "run_rank": int(run_rank),
            "pass_grade": float(pass_grade), "pass_rank": int(pass_rank),
            "overall_grade": float(overall_grade), "overall_rank": int(overall_rank),
            "rookies": int(rookies),
        } for overall_rank, team, run_grade, run_rank, pass_grade, pass_rank,
              overall_grade, rookies in rows]
    rows = _table_rows(html, {"Team", "Proj Run Grade", "Proj Pass Grade", "Overall Rank"})
    return [{
        "team": row["Team"], "run_grade": _number(row["Proj Run Grade"]),
        "run_rank": int(_number(row["Run Rank"])), "pass_grade": _number(row["Proj Pass Grade"]),
        "pass_rank": int(_number(row["Pass Rank"])), "overall_grade": _number(row["Overall Grade"]),
        "overall_rank": int(_number(row["Overall Rank"])),
    } for row in rows]


def parse_sos(html: str) -> list[dict]:
    rows = _table_rows(html, {"TEAM", "QB", "RB", "WR", "TE"})
    return [{
        "team": row["TEAM"],
        "QB": int(_number(row["QB"])),
        "RB": int(_number(row["RB"])),
        "WR": int(_number(row["WR"])),
        "TE": int(_number(row["TE"])),
    } for row in rows]


async def fetch_external_context() -> dict:
    urls = [KTC_URL, OL_URL, *SOS_URLS.values()]
    async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS, timeout=60.0) as client:
        responses = await __import__("asyncio").gather(
            *[client.get(url) for url in urls], return_exceptions=True
        )

    payload = {"updated_at": datetime.now(timezone.utc).isoformat(), "sources": {}}
    parsers = [
        ("ktc", KTC_URL, parse_ktc),
        ("offensive_lines", OL_URL, parse_offensive_lines),
        ("weeks_1_13", SOS_URLS["weeks_1_13"], parse_sos),
        ("weeks_1_17", SOS_URLS["weeks_1_17"], parse_sos),
    ]
    for (name, url, parser), response in zip(parsers, responses):
        try:
            if isinstance(response, Exception):
                raise response
            response.raise_for_status()
            data = parser(response.text)
            payload["sources"][name] = {
                "status": "ok", "url": url, "provenance": "public_page", "data": data
            }
        except Exception as exc:
            payload["sources"][name] = {
                "status": "unavailable", "url": url, "error": str(exc), "data": []
            }
    return payload

