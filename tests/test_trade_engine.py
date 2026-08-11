from analysis_engine import build_external_indexes, normalize_name
from trade_engine import search_trade_packages, team_assets
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


def test_required_asset_blocks_closest_package_when_it_is_severe_overpay():
    target = {"player_id": "t", "name": "Target", "position": "WR", "market": {"value": 6000}}
    expensive = {"player_id": "x", "name": "Expensive", "position": "RB", "market": {"value": 9000}}
    analysis = {"lineup_slots": ["RB", "WR"], "teams": [
        {"roster_id": 1, "manager": {}, "players": [expensive], "draft_picks": [],
         "analysis": {"measured": {"ktc_value_by_position": {"RB": 9000}}}},
        {"roster_id": 2, "manager": {}, "players": [target], "draft_picks": [],
         "analysis": {"measured": {"ktc_value_by_position": {"WR": 6000}}}},
    ]}
    result = search_trade_packages(analysis, "t", 1, {}, include_asset_ids=["x"])
    offers = [offer for offer in result["recommendations"].values() if offer]
    assert offers == []
    assert result["constraint_status"]["no_safe_packages"] is True


def test_recommendation_slots_are_unique_and_exact_size_is_honored():
    target = {"player_id": "t", "name": "Target", "position": "WR", "market": {"value": 6000}}
    players = [
        {"player_id": str(i), "name": f"Asset {i}", "position": "RB", "market": {"value": value}}
        for i, value in enumerate([2500, 2200, 1800, 1600, 1400], 1)
    ]
    analysis = {"lineup_slots": ["RB", "WR"], "teams": [
        {"roster_id": 1, "manager": {}, "players": players, "draft_picks": [],
         "analysis": {"measured": {"ktc_value_by_position": {"RB": 9500}}}},
        {"roster_id": 2, "manager": {}, "players": [target], "draft_picks": [],
         "analysis": {"measured": {"ktc_value_by_position": {"WR": 6000}}}},
    ]}
    result = search_trade_packages(analysis, "t", 1, {}, min_assets=3, max_assets=3)
    offers = [offer for offer in result["recommendations"].values() if offer]
    signatures = [tuple(asset["id"] for asset in offer["assets"]) for offer in offers]
    assert all(len(signature) == 3 for signature in signatures)
    assert len(signatures) == len(set(signatures))


def test_pick_values_use_original_roster_projection_and_all_rounds():
    pick_team = {"roster_id": 1, "players": [], "draft_picks": [
        {"season": 2027, "round": 4, "original_roster_id": 2}
    ]}
    ktc = {
        normalize_name("2027 Early 4th"): {"value": 900},
        normalize_name("2027 Mid 4th"): {"value": 600},
        normalize_name("2027 Late 4th"): {"value": 300},
    }
    assets = team_assets(pick_team, ktc, {2: {
        "probabilities": {"early": .7, "mid": .2, "late": .1},
        "most_likely_bucket": "early", "confidence": "medium", "method": "test",
    }})
    assert assets[0]["name"] == "2027 Early 4th"
    assert assets[0]["value"] == 780
    assert assets[0]["pick_projection"]["confidence"] == "medium"

