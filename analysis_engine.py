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


def canonical_player_name(name):
    """Normalize common provider differences such as Jr. and III suffixes."""
    value = normalize_name(name)
    return re.sub(r"(?:jr|sr|ii|iii|iv|v)$", "", value)


def build_external_indexes(context):
    sources = context.get("sources") or {}
    data = lambda key: (sources.get(key) or {}).get("data") or []
    return {
        "ktc": {normalize_name(row.get("name")): row for row in data("ktc")},
        "ktc_canonical": {
            canonical_player_name(row.get("name")): row for row in data("ktc")
        },
        "ol": {normalize_team(row.get("team")): row for row in data("offensive_lines")},
        "sos_1_13": {normalize_team(row.get("team")): row for row in data("weeks_1_13")},
        "sos_1_17": {normalize_team(row.get("team")): row for row in data("weeks_1_17")},
    }


def enrich_player(player, indexes):
    team = normalize_team(player.get("team"))
    position = player.get("position")
    ktc = (
        indexes["ktc"].get(normalize_name(player.get("name")))
        or indexes["ktc_canonical"].get(canonical_player_name(player.get("name")))
    )
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


def build_projection_indexes(projections):
    rows = projections.get("data") or []
    return {
        "by_id": {str(row["player_id"]): row for row in rows if row.get("player_id")},
        "by_name": {normalize_name(row.get("name")): row for row in rows if row.get("name")},
        "by_canonical_name": {
            canonical_player_name(row.get("name")): row for row in rows if row.get("name")
        },
    }


def summarize_team(team, indexes, projection_indexes=None):
    players = [enrich_player(player, indexes) for player in team.get("players") or []]
    projection_indexes = projection_indexes or {
        "by_id": {}, "by_name": {}, "by_canonical_name": {},
    }
    position_values = defaultdict(int)
    total_value = starter_value = matched = 0
    projected_starter_points = 0.0
    starter_redraft_adps = []
    projected_starters_matched = starter_count = 0
    for player in players:
        is_starter = player.get("roster_slot") == "starter"
        if is_starter:
            starter_count += 1
            projection = (
                projection_indexes["by_id"].get(str(player.get("player_id")))
                or projection_indexes["by_name"].get(normalize_name(player.get("name")))
                or projection_indexes["by_canonical_name"].get(
                    canonical_player_name(player.get("name"))
                )
            )
            if projection and isinstance(projection.get("projected_points"), (int, float)):
                projected_starters_matched += 1
                projected_starter_points += float(projection["projected_points"])
                if isinstance(projection.get("redraft_adp"), (int, float)):
                    starter_redraft_adps.append(float(projection["redraft_adp"]))
        value = player["market"]["value"]
        if not isinstance(value, (int, float)):
            continue
        matched += 1
        total_value += value
        position_values[player.get("position") or "OTHER"] += value
        if is_starter:
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
                "projected_starter_points": round(projected_starter_points, 2),
                "projected_starters_matched": projected_starters_matched,
                "starter_count": starter_count,
                "average_starter_redraft_adp": (
                    round(sum(starter_redraft_adps) / len(starter_redraft_adps), 2)
                    if starter_redraft_adps else None
                ),
                "starter_redraft_adp_matched": len(starter_redraft_adps),
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


def _rank_score(rank, team_count):
    """Convert league rank to a 0-100 score without pretending it is a forecast."""
    if team_count <= 1:
        return 100.0
    return round(100 * (team_count - rank) / (team_count - 1), 1)


def build_league_analysis(league_map, context, projections=None):
    indexes = build_external_indexes(context)
    projection_indexes = build_projection_indexes(projections or {})
    teams = [
        summarize_team(team, indexes, projection_indexes)
        for team in league_map.get("teams") or []
    ]
    for team in teams:
        team["analysis"]["league_relative"] = {}
    for metric in (
        "ktc_total_player_value", "ktc_starter_value", "future_first_count",
        "projected_starter_points",
    ):
        _rank(teams, metric)
    team_count = len(teams)
    playoff_slots = int(
        (league_map.get("league") or {}).get("settings", {}).get("playoff_teams")
        or max(1, team_count // 2)
    )
    for team in teams:
        measured = team["analysis"]["measured"]
        coverage = (
            measured["projected_starters_matched"] / measured["starter_count"]
            if measured["starter_count"] else 0
        )
        window = team["analysis"]["competitive_window"]
        window["projection_coverage"] = round(coverage, 3)
        relative = team["analysis"]["league_relative"]
        has_projections = coverage >= 0.7
        adp_coverage = (
            measured["starter_redraft_adp_matched"] / measured["starter_count"]
            if measured["starter_count"] else 0
        )
        production_rank = relative[
            "projected_starter_points_rank" if has_projections
            else "ktc_starter_value_rank"
        ]
        market_rank = team["analysis"]["league_relative"]["ktc_starter_value_rank"]
        total_value_rank = relative["ktc_total_player_value_rank"]
        firsts_rank = relative["future_first_count_rank"]
        current_score = round(
            0.65 * _rank_score(production_rank, team_count)
            + 0.25 * _rank_score(market_rank, team_count)
            + 0.10 * _rank_score(total_value_rank, team_count),
            1,
        )
        future_score = round(
            0.70 * _rank_score(total_value_rank, team_count)
            + 0.30 * _rank_score(firsts_rank, team_count),
            1,
        )
        if current_score >= 70:
            classification = "contender"
        elif current_score >= 52:
            classification = "playoff_bubble"
        elif current_score >= 32 or future_score >= 55:
            classification = "retooling"
        else:
            classification = "rebuild_candidate"
        window.update({
            "classification": classification,
            "current_strength_score": current_score,
            "future_strength_score": future_score,
            "power_rank": None,
            "confidence": "high" if has_projections and adp_coverage >= 0.7 else ("medium" if has_projections else "low"),
            "production_basis": (
                "2026 projected starter points corroborated by redraft ADP" if has_projections and adp_coverage >= 0.7
                else "2026 projected starter points" if has_projections
                else "KTC starter market value proxy"
            ),
            "reason": (
                "League-relative current strength blends production, starter quality, "
                "and roster depth. When projections are unavailable, starter market "
                "value is used as a clearly labeled low-confidence proxy."
            ),
            "heuristic": True,
        })
    ordered_strength = sorted(
        teams,
        key=lambda team: team["analysis"]["competitive_window"]["current_strength_score"],
        reverse=True,
    )
    for power_rank, team in enumerate(ordered_strength, 1):
        team["analysis"]["competitive_window"]["power_rank"] = power_rank
    return {
        "updated_at": league_map.get("updated_at"),
        "league_id": league_map.get("league_id"),
        "lineup_slots": league_map.get("roster_positions") or [],
        "methodology": {
            "measured": ["Sleeper roster state", "KTC market values", "draft-pick counts"],
            "sourced_context": ["4for4 offensive line", "FFToolbox SOS W1-13/W1-17"],
            "projection_source_status": (projections or {}).get("status", "not_configured"),
            "projection_source": (projections or {}).get("source_type"),
            "projection_updated_at": (projections or {}).get("updated_at"),
            "projection_cache": (projections or {}).get("cache"),
            "projected_players_available": len((projections or {}).get("data") or []),
            "window_rule": (
                "Current strength is 65% production signal, 25% starter market value, "
                "and 10% total roster value. Configured projections are used at >=70% "
                "starter coverage; otherwise KTC starter value is a low-confidence proxy."
            ),
        },
        "teams": teams,
    }

