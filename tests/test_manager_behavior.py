from manager_behavior import build_manager_profiles, infer_manager_objectives


def test_manager_profile_measures_pick_and_package_preferences():
    history = {"transactions": [{
        "type": "trade",
        "managers": [
            {"roster_id": 1, "user_id": "u1", "username": "one"},
            {"roster_id": 2, "user_id": "u2", "username": "two"},
        ],
        "adds": [
            {"roster_id": 1, "player_name": "Player A"},
            {"roster_id": 1, "player_name": "Player B"},
        ],
        "drops": [{"roster_id": 1, "player_name": "Player C"}],
        "draft_picks": [
            {"owner_id": 1, "previous_owner_id": 2},
        ],
    }]}
    ktc = {
        "playera": {"value": 1000, "position": "WR"},
        "playerb": {"value": 900, "position": "RB"},
        "playerc": {"value": 1500, "position": "QB"},
    }
    profile = build_manager_profiles(history, ktc)["u1"]
    assert profile["picks_acquired"] == 1
    assert profile["derived_tendencies"]["net_pick_buyer"] is True
    assert profile["positions_acquired"] == {"WR": 1, "RB": 1}


def test_manager_objective_is_labeled_as_low_confidence_guess_for_small_sample():
    profiles = {"u1": {"completed_trades": 1, "picks_acquired": 2,
                       "picks_sent": 0, "derived_tendencies": {"net_pick_buyer": True}}}
    analysis = {"teams": [{"roster_id": 1, "manager": {"user_id": "u1"},
        "analysis": {"competitive_window": {"classification": "rebuild_candidate",
        "current_strength_score": 20, "confidence": "low"}}}]}
    result = infer_manager_objectives(profiles, analysis)["u1"]["inferred_objective"]
    assert result["label"] == "accumulating_future_value"
    assert result["confidence"] == "low"
