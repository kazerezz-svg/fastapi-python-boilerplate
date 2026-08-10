Exit code: 0
Wall time: 1.1 seconds
Output:
"""Bounded trade-package generation with transparent value and fit heuristics."""
import itertools

from analysis_engine import normalize_name
from lineup_impact import simulate_market_trade, starter_slots


def _pick_label(pick, quality="Mid"):
    suffix = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(pick.get("round"))
    return f"{pick.get('season')} {quality} {suffix}" if suffix else None


def team_assets(team, ktc_index):
    assets = []
    for player in team.get("players") or []:
        value = (player.get("market") or {}).get("value")
        if isinstance(value, (int, float)):
            assets.append({
                "asset_type": "player", "id": str(player.get("player_id")),
                "name": player.get("name"), "position": player.get("position"),
                "value": value, "valuation": "KTC current market",
            })
    for pick in team.get("draft_picks") or []:
        label = _pick_label(pick)
        benchmark = ktc_index.get(normalize_name(label)) if label else None
        if benchmark and isinstance(benchmark.get("value"), (int, float)):
            assets.append({
                "asset_type": "pick",
                "id": f"{pick.get('season')}-{pick.get('round')}-{pick.get('original_roster_id')}",
                "name": label, "value": benchmark["value"],
                "season": pick.get("season"), "round": pick.get("round"),
                "original_roster_id": pick.get("original_roster_id"),
                "valuation": "KTC neutral-mid benchmark",
                "assumption": "Pick quality is unknown; Mid is a neutral liquidity benchmark.",
            })
    return assets


def _position_need(team, position):
    values = team["analysis"]["measured"].get("ktc_value_by_position") or {}
    position_value = values.get(position, 0)
    total = sum(values.values()) or 1
    return round(1 - position_value / total, 3)


def search_trade_packages(
    league_analysis, target_player_id, buyer_roster_id, ktc_index,
    manager_profiles=None,
):
    teams = league_analysis.get("teams") or []
    buyer = next((t for t in teams if t.get("roster_id") == buyer_roster_id), None)
    seller = None
    target = None
    for team in teams:
        for player in team.get("players") or []:
            if str(player.get("player_id")) == str(target_player_id):
                seller, target = team, player
                break
    if not buyer or not seller or not target:
        raise ValueError("buyer roster or target player not found")
    if buyer.get("roster_id") == seller.get("roster_id"):
        raise ValueError("buyer already owns target player")
    target_value = (target.get("market") or {}).get("value")
    if not isinstance(target_value, (int, float)):
        raise ValueError("target has no matched KTC value")
    seller_user_id = str((seller.get("manager") or {}).get("user_id") or "")
    seller_profile = (manager_profiles or {}).get(seller_user_id) or {}
    tendencies = seller_profile.get("derived_tendencies") or {}

    assets = sorted(team_assets(buyer, ktc_index), key=lambda a: a["value"], reverse=True)
    # Keep the search systematic but bounded for API latency and intelligibility.
    candidates = assets[:24]
    packages = []
    for size in (1, 2):
        for combo in itertools.combinations(candidates, size):
            value = sum(asset["value"] for asset in combo)
            ratio = value / target_value
            if not 0.72 <= ratio <= 1.30:
                continue
            pick_count = sum(asset["asset_type"] == "pick" for asset in combo)
            replacement = sum(
                asset["asset_type"] == "player"
                and asset.get("position") == target.get("position")
                for asset in combo
            )
            seller_fit = round(
                0.55 * min(ratio, 1.15) / 1.15
                + 0.25 * min(pick_count, 1)
                + 0.20 * min(replacement, 1),
                3,
            )
            behavior_adjustment = 0.0
            if tendencies.get("net_pick_buyer") and pick_count:
                behavior_adjustment += 0.08
            if tendencies.get("prefers_two_for_one_returns") and size == 2:
                behavior_adjustment += 0.06
            seller_fit = round(min(1.0, seller_fit + behavior_adjustment), 3)
            buyer_fit = _position_need(buyer, target.get("position"))
            fairness = round(1 - min(abs(1 - ratio), 0.5) / 0.5, 3)
            lineup = simulate_market_trade(
                buyer, seller, target, {"assets": list(combo)},
                starter_slots(league_analysis.get("lineup_slots")),
            )
            buyer_lineup_fit = max(0.0, min(1.0, lineup["buyer"]["delta"] / 1500 + 0.5))
            score = round(
                0.40 * fairness + 0.25 * seller_fit
                + 0.15 * buyer_fit + 0.20 * buyer_lineup_fit,
                3,
            )
            packages.append({
                "assets": list(combo), "package_value": value,
                "target_value": target_value, "value_ratio": round(ratio, 3),
                "buyer_position_need": buyer_fit, "seller_incentive": seller_fit,
                "manager_behavior_adjustment": round(behavior_adjustment, 3),
                "fairness": fairness, "score": score,
                "lineup_impact": lineup,
            })
    packages.sort(key=lambda package: package["score"], reverse=True)

    def best(low, high):
        return next((p for p in packages if low <= p["value_ratio"] <= high), None)

    return {
        "target": {
            "player_id": str(target_player_id), "name": target.get("name"),
            "position": target.get("position"), "value": target_value,
            "seller": seller.get("manager"), "seller_roster_id": seller.get("roster_id"),
        },
        "buyer": buyer.get("manager"),
        "recommendations": {
            "opening_offer": best(0.88, 0.98),
            "fair_value": best(0.98, 1.08),
            "walk_away_price": best(1.08, 1.18),
            "plausible_counter": best(1.00, 1.12),
        },
        "ranked_packages": packages[:20],
        "methodology": {
            "measured": "KTC benchmark values and roster positional market composition",
            "heuristics": (
                "40% value fairness, 25% seller incentive, 15% buyer positional "
                "need, 20% optimized-lineup market impact"
            ),
            "limits": "One- and two-asset combinations from the buyer's top 24 valued assets.",
            "manager_history": {
                "seller_sample_size": seller_profile.get("completed_trades", 0),
                "tendencies": tendencies,
                "maximum_score_adjustment": 0.14,
            },
        },
    }

