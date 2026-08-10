Exit code: 0
Wall time: 1.1 seconds
Output:
from intelligence import pick_outlooks, player_sell_evidence, scan_young_targets


def team(rid, player, rank):
    return {
        "roster_id": rid, "players": [player] if player else [],
        "analysis": {
            "measured": {"ktc_value_by_position": {"WR": 5000}},
            "league_relative": {
                "ktc_starter_value_rank": rank,
                "projected_starter_points_rank": rank,
            },
            "competitive_window": {
                "classification": "insufficient_projection_data",
                "projection_coverage": 0,
            },
        },
    }


def test_young_target_scan_and_pick_outlook_are_labeled():
    player = {
        "player_id": "1", "name": "Young WR", "position": "WR", "age": 22,
        "market": {"value": 5000, "rank": 20},
        "strength_of_schedule": {}, "offensive_line": {},
    }
    analysis = {"teams": [team(1, None, 1), team(2, player, 2)]}
    assert scan_young_targets(analysis, 1)[0]["name"] == "Young WR"
    outlook = pick_outlooks(analysis)[1]
    assert outlook["confidence"] == "low"
    assert sum(outlook["probabilities"].values()) > 0.99


def test_sell_evidence_withholds_confident_call_without_projections():
    player = {
        "position": "WR", "roster_slot": "starter", "market": {"value": 4000},
        "strength_of_schedule": {}, "offensive_line": {},
    }
    result = player_sell_evidence(player, team(1, player, 1))
    assert result["recommendation"] == "hold_or_listen"

