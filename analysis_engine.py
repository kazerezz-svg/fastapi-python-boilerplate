Exit code: 0
Wall time: 1 seconds
Output:
"""Evidence-aware joins and league-relative roster analysis."""
import re
import unicodedata
from collections import defaultdict

TEAM_ALIASES = {
    "ARI": "ARI", "ARZ": "ARI", "JAC": "JAX", "JAX": "JAX",
    "GB": "GB", "GBP": "GB", "KC": "KC", "KCC": "KC",
    "LV": "LV", "LVR": "LV", "NE": "NE", "NEP": "NE",
    "NO": "NO", "NOS": "NO", "SF": "SF", "SFO": "SF",
    "TB": "TB", "TBB": "TB",
}


def normalize_team(team):
    value = str(team or "").upper()
    return TEAM_ALIASES.get(value, value)


def normalize_name(name):
    value = unicodedata.normalize("NFKD", str(name or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", value.lower())


def build_external_indexes(context):
    sources = context.get("sources") or {}
    data = lambda key: (sources.get(key) or {}).get("data") or []
    return {
        "ktc": {normalize_name(row.get("name")): row for row in data("ktc")},
        "ol": {normalize_team(row.get("team")): row for row in data("offensive_lines")},
        "sos_1_13": {normalize_team(row.get("team")): row for row in data("weeks_1_13")},
        "sos_1_17": {normalize_team(row.get("team")): row for row in data("weeks_1_17")},
    }


def enrich_player(player, indexes):
    team = normalize_team(player.get("team"))
    position = player.get("position")
    ktc = indexes["ktc"].get(normalize_name(player.get("name")))
    return {
        **player,
        "normalized_team": team,
        "market": {
            "source": "KeepTradeCut",
            "status": "matched" if ktc else "unmatched",
            "value": ktc.get("value") if ktc else None,
            "rank": ktc.get("rank") if ktc else None,
            "positional_rank": ktc.get("positional_rank") if ktc else None,
            "tier": ktc.get("tier") if ktc else None,
        },
        "offensive_line": {
            "source": "4for4",
            "relevant": position in {"QB", "RB", "WR", "TE"},
            "data": indexes["ol"].get(team),
        },
        "strength_of_schedule": {
            "source": "FFToolbox",
            "position": position,
            "weeks_1_13_rank": (indexes["sos_1_13"].get(team) or {}).get(position),
            "weeks_1_17_rank": (indexes["sos_1_17"].get(team) or {}).get(position),
            "interpretation": "1=easiest, 32=hardest",
        },
        "provenance": {
            "identity_roster_age": "Sleeper",
            "market": "public_crowdsourced_benchmark",
            "offensive_line": "public_projection",
            "sos": "public_schedule_rank",
        },
    }


def summarize_team(team, indexes):
    players = [enrich_player(player, indexes) for player in team.get("players") or []]
    position_values = defaultdict(int)
    total_value = starter_value = matched = 0
    for player in players:
        value = player["market"]["value"]
        if not isinstance(value, (int, float)):
            continue
        matched += 1
        total_value += value
        position_values[player.get("position") or "OTHER"] += value
        if player.get("roster_slot") == "starter":
            starter_value += value
    picks = team.get("draft_picks") or []
    return {
        **team,
        "players": players,
        "analysis": {
            "measured": {
                "ktc_total_player_value": total_value,
                "ktc_starter_value": starter_value,
                "ktc_value_by_position": dict(position_values),
                "ktc_players_matched": matched,
                "player_count": len(players),
                "future_pick_count": len(picks),
                "future_first_count": sum(1 for pick in picks if pick.get("round") == 1),
            },
            "competitive_window": {
                "classification": "insufficient_projection_data",
                "reason": (
                    "Market value and roster depth are measured, but a defensible "
                    "contender/rebuilder label also requires projected production."
                ),
            },
        },
    }


def _rank(teams, metric):
    ordered = sorted(
        teams, key=lambda team: team["analysis"]["measured"][metric], reverse=True
    )
    for rank, team in enumerate(ordered, 1):
        team["analysis"]["league_relative"][f"{metric}_rank"] = rank


def build_league_analysis(league_map, context):
    indexes = build_external_indexes(context)
    teams = [summarize_team(team, indexes) for team in league_map.get("teams") or []]
    for team in teams:
        team["analysis"]["league_relative"] = {}
    for metric in ("ktc_total_player_value", "ktc_starter_value", "future_first_count"):
        _rank(teams, metric)
    return {
        "updated_at": league_map.get("updated_at"),
        "league_id": league_map.get("league_id"),
        "methodology": {
            "measured": ["Sleeper roster state", "KTC market values", "draft-pick counts"],
            "sourced_context": ["4for4 offensive line", "FFToolbox SOS W1-13/W1-17"],
            "withheld": ["competitive-window classification pending projections"],
        },
        "teams": teams,
    }

