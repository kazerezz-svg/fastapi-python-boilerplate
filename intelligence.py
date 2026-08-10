"""Higher-level scans built from the evidence-aware league analysis."""
import math


def scan_young_targets(analysis, buyer_roster_id, position="WR", max_age=24):
    buyer = next(t for t in analysis["teams"] if t["roster_id"] == buyer_roster_id)
    results = []
    for team in analysis["teams"]:
        if team["roster_id"] == buyer_roster_id:
            continue
        for player in team["players"]:
            if player.get("position") != position:
                continue
            age = player.get("age")
            value = player["market"].get("value")
            if not isinstance(age, (int, float)) or age > max_age or not value:
                continue
            results.append({
                "player_id": player["player_id"], "name": player["name"], "age": age,
                "owner": team.get("manager"), "roster_id": team["roster_id"],
                "ktc_value": value, "ktc_rank": player["market"].get("rank"),
                "sos": player["strength_of_schedule"],
                "offensive_line": player["offensive_line"],
                "buyer_position_value": buyer["analysis"]["measured"][
                    "ktc_value_by_position"
                ].get(position, 0),
            })
    results.sort(key=lambda row: (row["ktc_value"], -row["age"]), reverse=True)
    return results


def pick_outlooks(analysis):
    teams = analysis["teams"]
    count = max(len(teams), 1)
    output = []
    for team in teams:
        ranks = team["analysis"]["league_relative"]
        market_rank = ranks["ktc_starter_value_rank"]
        production_rank = ranks["projected_starter_points_rank"]
        coverage = team["analysis"]["competitive_window"].get("projection_coverage", 0)
        effective_rank = (
            0.55 * production_rank + 0.45 * market_rank
            if coverage >= 0.7 else market_rank
        )
        weakness = (effective_rank - 1) / max(count - 1, 1)
        early_weight = math.exp(3 * (weakness - 0.5))
        late_weight = math.exp(3 * (0.5 - weakness))
        mid_weight = 1.2
        total = early_weight + mid_weight + late_weight
        probabilities = {
            "early": round(early_weight / total, 3),
            "mid": round(mid_weight / total, 3),
            "late": round(late_weight / total, 3),
        }
        output.append({
            "original_roster_id": team["roster_id"], "manager": team.get("manager"),
            "probabilities": probabilities,
            "inputs": {
                "starter_market_rank": market_rank,
                "projected_starter_rank": production_rank if coverage >= 0.7 else None,
                "projection_coverage": coverage,
            },
            "confidence": "medium" if coverage >= 0.7 else "low",
            "method": (
                "league-relative starter projection and market ranks"
                if coverage >= 0.7 else
                "market-only preseason estimate; projections unavailable"
            ),
        })
    return output


def player_sell_evidence(player, team):
    position = player.get("position")
    measured = team["analysis"]["measured"]
    value = player["market"].get("value")
    position_total = measured["ktc_value_by_position"].get(position, 0) or 1
    share = round(value / position_total, 3) if value else None
    window = team["analysis"]["competitive_window"]
    if window["classification"] == "insufficient_projection_data":
        recommendation = "hold_or_listen"
        reason = "Projection coverage is insufficient for a confident sell decision."
    elif window["classification"] == "rebuild_candidate" and value:
        recommendation = "actively_shop_if_return_improves_window"
        reason = "Team projects outside the playoff field; prioritize liquid value."
    else:
        recommendation = "hold_unless_lineup_neutral_overpay"
        reason = "Competitive-window and lineup value favor retaining production."
    return {
        "recommendation": recommendation, "reason": reason,
        "evidence": {
            "ktc_value": value, "share_of_team_position_value": share,
            "lineup_slot": player.get("roster_slot"),
            "competitive_window": window,
            "sos": player["strength_of_schedule"],
            "offensive_line": player["offensive_line"],
        },
        "heuristic": True,
    }

