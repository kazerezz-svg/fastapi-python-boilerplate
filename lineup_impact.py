Exit code: 0
Wall time: 1.1 seconds
Output:
"""Greedy lineup optimization for transparent before/after trade deltas."""

ELIGIBLE = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"},
    "FLEX": {"RB", "WR", "TE"}, "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}


def starter_slots(roster_positions):
    return [slot for slot in roster_positions or [] if slot in ELIGIBLE]


def optimal_lineup(players, slots, value_getter):
    remaining = list(players)
    selected = []
    # Fill restrictive slots first, then flex positions.
    ordered_slots = sorted(slots, key=lambda slot: len(ELIGIBLE[slot]))
    for slot in ordered_slots:
        eligible = [
            player for player in remaining
            if player.get("position") in ELIGIBLE[slot]
            and isinstance(value_getter(player), (int, float))
        ]
        if not eligible:
            continue
        player = max(eligible, key=value_getter)
        selected.append({"slot": slot, "player_id": str(player.get("player_id")),
                         "name": player.get("name"), "value": value_getter(player)})
        remaining.remove(player)
    return {"value": round(sum(item["value"] for item in selected), 2),
            "filled_slots": len(selected), "lineup": selected}


def market_value(player):
    return (player.get("market") or {}).get("value")


def simulate_market_trade(buyer, seller, target, package, slots):
    outgoing_ids = {
        asset["id"] for asset in package.get("assets") or []
        if asset.get("asset_type") == "player"
    }
    buyer_players = buyer.get("players") or []
    seller_players = seller.get("players") or []
    incoming_players = [
        player for player in buyer_players
        if str(player.get("player_id")) in outgoing_ids
    ]
    buyer_after = [
        player for player in buyer_players
        if str(player.get("player_id")) not in outgoing_ids
    ] + [target]
    seller_after = [
        player for player in seller_players
        if str(player.get("player_id")) != str(target.get("player_id"))
    ] + incoming_players
    buyer_before = optimal_lineup(buyer_players, slots, market_value)
    buyer_after_result = optimal_lineup(buyer_after, slots, market_value)
    seller_before = optimal_lineup(seller_players, slots, market_value)
    seller_after_result = optimal_lineup(seller_after, slots, market_value)
    return {
        "buyer": {
            "before": buyer_before["value"], "after": buyer_after_result["value"],
            "delta": round(buyer_after_result["value"] - buyer_before["value"], 2),
        },
        "seller": {
            "before": seller_before["value"], "after": seller_after_result["value"],
            "delta": round(seller_after_result["value"] - seller_before["value"], 2),
        },
        "metric": "KTC market value of optimized starting lineup",
        "limitation": "Market lineup impact is not a points projection.",
    }

