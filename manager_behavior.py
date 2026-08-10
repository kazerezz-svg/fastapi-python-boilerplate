Exit code: 0
Wall time: 1.1 seconds
Output:
"""Measured manager trade tendencies from normalized Sleeper history."""
from collections import Counter, defaultdict

from analysis_engine import normalize_name


def build_manager_profiles(history, ktc_index):
    profiles = defaultdict(lambda: {
        "completed_trades": 0, "players_acquired": 0, "players_sent": 0,
        "picks_acquired": 0, "picks_sent": 0, "value_acquired": 0,
        "value_sent": 0, "received_multi_asset_for_one": 0,
        "sent_multi_asset_for_one": 0, "trade_partners": Counter(),
        "positions_acquired": Counter(),
    })
    for tx in history.get("transactions") or []:
        if tx.get("type") != "trade":
            continue
        managers = tx.get("managers") or []
        for manager in managers:
            user_id = str(manager.get("user_id") or "")
            roster_id = manager.get("roster_id")
            if not user_id or roster_id is None:
                continue
            profile = profiles[user_id]
            profile["completed_trades"] += 1
            for partner in managers:
                if partner.get("roster_id") != roster_id:
                    name = partner.get("username") or partner.get("team_name")
                    if name:
                        profile["trade_partners"][name] += 1
            acquired = [item for item in tx.get("adds") or [] if item.get("roster_id") == roster_id]
            sent = [item for item in tx.get("drops") or [] if item.get("roster_id") == roster_id]
            acquired_picks = [
                pick for pick in tx.get("draft_picks") or []
                if pick.get("owner_id") == roster_id
            ]
            sent_picks = [
                pick for pick in tx.get("draft_picks") or []
                if pick.get("previous_owner_id") == roster_id
            ]
            profile["players_acquired"] += len(acquired)
            profile["players_sent"] += len(sent)
            profile["picks_acquired"] += len(acquired_picks)
            profile["picks_sent"] += len(sent_picks)
            received_count = len(acquired) + len(acquired_picks)
            sent_count = len(sent) + len(sent_picks)
            if received_count >= 2 and sent_count == 1:
                profile["received_multi_asset_for_one"] += 1
            if sent_count >= 2 and received_count == 1:
                profile["sent_multi_asset_for_one"] += 1
            for item, direction in [(x, "acquired") for x in acquired] + [
                (x, "sent") for x in sent
            ]:
                market = ktc_index.get(normalize_name(item.get("player_name"))) or {}
                value = market.get("value")
                if isinstance(value, (int, float)):
                    profile[f"value_{direction}"] += value
                if direction == "acquired" and market.get("position"):
                    profile["positions_acquired"][market["position"]] += 1

    output = {}
    for user_id, profile in profiles.items():
        trades = profile["completed_trades"]
        output[user_id] = {
            **{key: value for key, value in profile.items()
               if key not in {"trade_partners", "positions_acquired"}},
            "most_common_partners": [
                {"manager": name, "trades": count}
                for name, count in profile["trade_partners"].most_common(5)
            ],
            "positions_acquired": dict(profile["positions_acquired"]),
            "derived_tendencies": {
                "net_pick_buyer": profile["picks_acquired"] > profile["picks_sent"],
                "prefers_two_for_one_returns": (
                    profile["received_multi_asset_for_one"]
                    > profile["sent_multi_asset_for_one"]
                ),
            },
            "provenance": {
                "transactions": "measured completed Sleeper trades",
                "values": "current KTC applied retrospectively; not value at trade date",
                "tendencies": "descriptive heuristic, minimum sample not guaranteed",
                "sample_size": trades,
            },
        }
    return output

