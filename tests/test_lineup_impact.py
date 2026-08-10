Exit code: 0
Wall time: 1.1 seconds
Output:
from lineup_impact import optimal_lineup, simulate_market_trade, starter_slots


def player(pid, position, value):
    return {"player_id": pid, "name": pid, "position": position,
            "market": {"value": value}}


def test_optimizer_respects_superflex_and_flex():
    result = optimal_lineup(
        [player("q1", "QB", 5000), player("q2", "QB", 4000),
         player("r1", "RB", 3000), player("w1", "WR", 3500)],
        starter_slots(["QB", "RB", "WR", "SUPER_FLEX"]),
        lambda item: item["market"]["value"],
    )
    assert result["filled_slots"] == 4
    assert result["value"] == 15500


def test_trade_simulation_reports_both_sides():
    buyer = {"players": [player("b", "RB", 3000), player("x", "WR", 1000)]}
    seller = {"players": [player("t", "WR", 5000)]}
    target = seller["players"][0]
    package = {"assets": [{"asset_type": "player", "id": "b"}]}
    result = simulate_market_trade(buyer, seller, target, package, ["RB", "WR"])
    assert result["buyer"]["delta"] > 0
    assert result["seller"]["delta"] < 0

