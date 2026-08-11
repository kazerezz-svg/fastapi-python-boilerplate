"""Bounded trade-package generation with transparent value and fit heuristics."""
import itertools

from analysis_engine import normalize_name
from intelligence import pick_outlooks
from lineup_impact import simulate_market_trade, starter_slots


def _pick_label(pick, quality="Mid"):
    suffix = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(pick.get("round"))
    return f"{pick.get('season')} {quality} {suffix}" if suffix else None


def team_assets(team, ktc_index, pick_outlook_by_roster=None):
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
        outlook = (pick_outlook_by_roster or {}).get(pick.get("original_roster_id")) or {}
        probabilities = outlook.get("probabilities") or {"early": 0, "mid": 1, "late": 0}
        bucket_values = {}
        for bucket in ("early", "mid", "late"):
            bucket_label = _pick_label(pick, bucket.title())
            benchmark = ktc_index.get(normalize_name(bucket_label)) if bucket_label else None
            if benchmark and isinstance(benchmark.get("value"), (int, float)):
                bucket_values[bucket] = benchmark["value"]
        likely_bucket = outlook.get("most_likely_bucket") or "mid"
        value = sum(probabilities.get(bucket, 0) * bucket_values[bucket] for bucket in bucket_values)
        if not value and bucket_values:
            value = bucket_values.get(likely_bucket) or bucket_values.get("mid") or next(iter(bucket_values.values()))
        original_owner = (
            pick.get("original_owner_team")
            or pick.get("original_owner_username")
            or f"Roster {pick.get('original_roster_id')}"
        )
        benchmark_label = _pick_label(pick, likely_bucket.title())
        label = f"{benchmark_label} Â· from {original_owner}"
        if value:
            assets.append({
                "asset_type": "pick",
                "id": f"{pick.get('season')}-{pick.get('round')}-{pick.get('original_roster_id')}",
                "name": label, "value": round(value),
                "season": pick.get("season"), "round": pick.get("round"),
                "original_roster_id": pick.get("original_roster_id"),
                "original_owner": original_owner,
                "valuation": "Probability-weighted KTC early/mid/late pick value",
                "pick_projection": {
                    "probabilities": probabilities,
                    "most_likely_bucket": likely_bucket,
                    "confidence": outlook.get("confidence", "low"),
                    "method": outlook.get("method", "neutral mid fallback"),
                },
                "assumption": "Pick slot is projected from the original roster's strength and remains uncertain.",
            })
    return assets


def _position_need(team, position):
    values = team["analysis"]["measured"].get("ktc_value_by_position") or {}
    position_value = values.get(position, 0)
    total = sum(values.values()) or 1
    return round(1 - position_value / total, 3)


def search_trade_packages(
    league_analysis, target_player_id, buyer_roster_id, ktc_index,
    manager_profiles=None, include_asset_ids=None, exclude_asset_ids=None,
    package_style="balanced", min_assets=1, max_assets=2, receive_size=1,
    include_receive_asset_ids=None, exclude_receive_asset_ids=None,
):
    include_ids = {str(value) for value in (include_asset_ids or []) if value}
    exclude_ids = {str(value) for value in (exclude_asset_ids or []) if value}
    include_receive_ids = {str(value) for value in (include_receive_asset_ids or []) if value}
    exclude_receive_ids = {str(value) for value in (exclude_receive_asset_ids or []) if value}
    if include_ids & exclude_ids:
        raise ValueError("an asset cannot be both required and protected")
    valid_styles = {"balanced", "picks_heavy", "players_heavy", "two_for_one"}
    if package_style not in valid_styles:
        raise ValueError("package_style must be balanced, picks_heavy, players_heavy, or two_for_one")
    max_assets = max(1, min(int(max_assets), 3))
    min_assets = max(1, min(int(min_assets), max_assets))
    receive_size = max(1, min(int(receive_size), 3))
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

    has_picks = any(team.get("draft_picks") for team in teams)
    outlook_by_roster = (
        {item["original_roster_id"]: item for item in pick_outlooks(league_analysis)}
        if has_picks else {}
    )
    assets = sorted(
        team_assets(buyer, ktc_index, outlook_by_roster),
        key=lambda a: a["value"], reverse=True,
    )
    known_ids = {asset["id"] for asset in assets}
    missing = include_ids - known_ids
    if missing:
        raise ValueError(f"required asset not found on buyer roster: {', '.join(sorted(missing))}")
    assets = [asset for asset in assets if asset["id"] not in exclude_ids]
    # Keep the search systematic but bounded for API latency and intelligibility.
    player_candidates = [asset for asset in assets if asset["asset_type"] == "player"][:20]
    pick_candidates = [asset for asset in assets if asset["asset_type"] == "pick"]
    candidates = player_candidates + pick_candidates
    for required in (asset for asset in assets if asset["id"] in include_ids):
        if required not in candidates:
            candidates.append(required)
    packages = []
    near_misses = []
    for size in range(min_assets, max_assets + 1):
        for combo in itertools.combinations(candidates, size):
            combo_ids = {asset["id"] for asset in combo}
            if not include_ids.issubset(combo_ids):
                continue
            if package_style == "two_for_one" and size < 2:
                continue
            value = sum(asset["value"] for asset in combo)
            ratio = value / target_value
            search_upper = 1.30 if receive_size == 1 else 2.20
            in_standard_range = 0.72 <= ratio <= search_upper
            if not in_standard_range and not include_ids:
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
            player_count = size - pick_count
            style_adjustment = 0.0
            if package_style == "picks_heavy":
                style_adjustment = 0.10 * pick_count / size
            elif package_style == "players_heavy":
                style_adjustment = 0.10 * player_count / size
            elif package_style == "two_for_one":
                style_adjustment = 0.08 if size >= 2 else 0.0
            score = round(
                0.40 * fairness + 0.25 * seller_fit
                + 0.15 * buyer_fit + 0.20 * buyer_lineup_fit + style_adjustment,
                3,
            )
            package = {
                "assets": list(combo), "package_value": value,
                "target_value": target_value, "value_ratio": round(ratio, 3),
                "buyer_position_need": buyer_fit, "seller_incentive": seller_fit,
                "manager_behavior_adjustment": round(behavior_adjustment, 3),
                "package_style_adjustment": round(style_adjustment, 3),
                "fairness": fairness, "score": score,
                "lineup_impact": lineup,
                "outside_standard_range": not in_standard_range,
            }
            if in_standard_range:
                packages.append(package)
            elif ratio < 0.72:
                near_misses.append(package)
    if include_ids and not packages:
        near_misses.sort(key=lambda package: abs(1 - package["value_ratio"]))
        packages = near_misses[:20]
    packages.sort(key=lambda package: package["score"], reverse=True)

    target_asset = {
        "asset_type": "player", "id": str(target_player_id),
        "name": target.get("name"), "position": target.get("position"),
        "value": target_value, "valuation": "KTC current market",
    }
    if receive_size > 1:
        seller_assets = [
            asset for asset in team_assets(seller, ktc_index, outlook_by_roster)
            if asset["id"] != str(target_player_id) and asset["id"] not in exclude_receive_ids
        ]
        seller_known = {asset["id"] for asset in seller_assets}
        missing_receive = include_receive_ids - seller_known
        if missing_receive:
            raise ValueError(f"required received asset not found on seller roster: {', '.join(sorted(missing_receive))}")
        seller_players = sorted(
            [asset for asset in seller_assets if asset["asset_type"] == "player"],
            key=lambda asset: asset["value"], reverse=True,
        )[:16]
        seller_picks = [asset for asset in seller_assets if asset["asset_type"] == "pick"]
        receive_candidates = seller_players + seller_picks
        extra_sets = [
            combo for combo in itertools.combinations(receive_candidates, receive_size - 1)
            if include_receive_ids.issubset({asset["id"] for asset in combo})
        ]
        expanded = []
        for package in packages[:120]:
            for extras in extra_sets:
                received = [target_asset, *extras]
                received_value = sum(asset["value"] for asset in received)
                ratio = package["package_value"] / received_value
                if not 0.72 <= ratio <= 1.30:
                    continue
                fairness = round(1 - min(abs(1 - ratio), 0.5) / 0.5, 3)
                variant = dict(package)
                variant.update({
                    "receive_assets": received,
                    "target_value": received_value,
                    "value_ratio": round(ratio, 3),
                    "fairness": fairness,
                    "score": round(package["score"] - 0.40 * package["fairness"] + 0.40 * fairness, 3),
                })
                expanded.append(variant)
        packages = sorted(expanded, key=lambda package: package["score"], reverse=True)
    else:
        for package in packages:
            package["receive_assets"] = [target_asset]

    used_signatures = set()

    def pick_unique(low, high, anchor, prefer_size=None):
        available = [
            package for package in packages
            if (
                tuple(asset["id"] for asset in package["assets"]),
                tuple(asset["id"] for asset in package["receive_assets"]),
            ) not in used_signatures
        ]
        if prefer_size:
            sized = [package for package in available if len(package["assets"]) == prefer_size]
            if sized:
                available = sized
        in_band = [package for package in available if low <= package["value_ratio"] <= high]
        pool = in_band or (available if include_ids or receive_size > 1 else [])
        if not pool:
            return None
        choice = min(pool, key=lambda package: (abs(anchor - package["value_ratio"]), -package["score"]))
        used_signatures.add((
            tuple(asset["id"] for asset in choice["assets"]),
            tuple(asset["id"] for asset in choice["receive_assets"]),
        ))
        return choice

    used_near_miss = bool(packages and all(p["outside_standard_range"] for p in packages))
    no_safe_packages = not packages
    recommendations = {
        "opening_offer": pick_unique(0.88, 0.98, 0.93, min_assets),
        "fair_value": pick_unique(0.98, 1.08, 1.03),
        "plausible_counter": pick_unique(1.00, 1.12, 1.06, max_assets),
        "walk_away_price": pick_unique(1.08, 1.18, 1.13),
    }

    return {
        "target": {
            "player_id": str(target_player_id), "name": target.get("name"),
            "position": target.get("position"), "value": target_value,
            "seller": seller.get("manager"), "seller_roster_id": seller.get("roster_id"),
        },
        "buyer": buyer.get("manager"),
        "constraints_applied": {
            "engine_version": "two-sided-v1",
            "include_asset_ids": sorted(include_ids),
            "exclude_asset_ids": sorted(exclude_ids),
            "package_style": package_style,
            "min_assets": min_assets,
            "max_assets": max_assets,
            "receive_size": receive_size,
            "include_receive_asset_ids": sorted(include_receive_ids),
            "exclude_receive_asset_ids": sorted(exclude_receive_ids),
        },
        "constraint_status": {
            "used_closest_packages": used_near_miss,
            "no_safe_packages": no_safe_packages,
            "message": (
                "No package of this exact size stays at or below 130% of the target's KTC value. "
                "Try fewer assets or include a projected pick; the finder will not recommend a severe overpay."
                if no_safe_packages else
                "No package with the required asset lands inside the normal 72%-130% KTC search range. "
                "Showing only the closest underpay constructions; packages above 130% are blocked as unhelpful overpays."
                if used_near_miss else
                "Packages satisfy the selected constraints and the normal KTC search range."
            ),
        },
        "recommendations": recommendations,
        "ranked_packages": packages[:20],
        "methodology": {
            "measured": "KTC player values, probability-weighted early/mid/late KTC pick values, and roster composition",
            "heuristics": (
                "40% value fairness, 25% seller incentive, 15% buyer positional "
                "need, 20% optimized-lineup market impact"
            ),
            "limits": f"Bounded {min_assets}-{max_assets} outgoing by {receive_size} incoming search; primary target required, secondary seller candidates limited to relevant players and all picks.",
            "manager_history": {
                "seller_sample_size": seller_profile.get("completed_trades", 0),
                "tendencies": tendencies,
                "maximum_score_adjustment": 0.14,
            },
        },
    }

