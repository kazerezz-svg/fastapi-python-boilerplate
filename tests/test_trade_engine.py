Exit code: 0
Wall time: 1.3 seconds
Output:
from analysis_engine import build_external_indexes
from trade_engine import search_trade_packages
from test_analysis_engine import CONTEXT


def test_trade_search_returns_offer_bands_and_mutual_incentives():
    target = {"player_id": "t", "name": "Carnell Tate", "position": "WR",
              "market": {"value": 5975}}
    buyer_player = {"player_id": "b", "name": "Buyer RB", "position": "RB",
                    "market": {"value": 5500}}
    analysis = {"lineup_slots": ["RB", "WR"], "teams": [
        {"roster_id": 1, "manager": {"username": "buyer"}, "players": [buyer_player],
         "draft_picks": [], "analysis": {"measured": {
             "ktc_value_by_position": {"RB": 5500}}}},
        {"roster_id": 2, "manager": {"username": "seller"}, "players": [target],
         "draft_picks": [], "analysis": {"measured": {
             "ktc_value_by_position": {"WR": 5975}}}},
    ]}
    result = search_trade_packages(
        analysis, "t", 1, build_external_indexes(CONTEXT)["ktc"],
        {"": {"completed_trades": 3, "derived_tendencies": {
            "net_pick_buyer": True, "prefers_two_for_one_returns": True}}},
    )
    assert result["recommendations"]["opening_offer"]["assets"][0]["name"] == "Buyer RB"
    assert result["ranked_packages"][0]["seller_incentive"] >= 0
    assert "lineup_impact" in result["ranked_packages"][0]
    assert result["methodology"]["heuristics"]


def test_trade_search_rejects_buying_own_player():
    analysis = {"lineup_slots": ["WR"], "teams": [{"roster_id": 1, "players": [
        {"player_id": "t", "name": "Carnell Tate", "position": "WR",
         "market": {"value": 5975}}
    ], "draft_picks": [], "analysis": {"measured": {"ktc_value_by_position": {}}}}]}
    try:
        search_trade_packages(analysis, "t", 1, {})
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "already owns" in str(exc)


def test_trade_search_honors_required_protected_and_style_constraints():
    target = {"player_id": "t", "name": "Target WR", "position": "WR",
              "market": {"value": 6000}}
    players = [
        {"player_id": "must", "name": "Must Include", "position": "RB", "market": {"value": 3500}},
        {"player_id": "protect", "name": "Protected", "position": "WR", "market": {"value": 5000}},
        {"player_id": "helper", "name": "Helper", "position": "QB", "market": {"value": 2600}},
    ]
    analysis = {"lineup_slots": ["QB", "RB", "WR"], "teams": [
        {"roster_id": 1, "manager": {"username": "buyer"}, "players": players,
         "draft_picks": [], "analysis": {"measured": {"ktc_value_by_position": {"RB": 3500, "WR": 5000, "QB": 2600}}}},
        {"roster_id": 2, "manager": {"username": "seller"}, "players": [target],
         "draft_picks": [], "analysis": {"measured": {"ktc_value_by_position": {"WR": 6000}}}},
    ]}
    result = search_trade_packages(
        analysis, "t", 1, {}, include_asset_ids=["must"],
        exclude_asset_ids=["protect"], package_style="two_for_one", max_assets=3,
    )
    assert result["ranked_packages"]
    for package in result["ranked_packages"]:
        ids = {asset["id"] for asset in package["assets"]}
        assert "must" in ids and "protect" not in ids and len(ids) >= 2
    assert result["constraints_applied"]["package_style"] == "two_for_one"

