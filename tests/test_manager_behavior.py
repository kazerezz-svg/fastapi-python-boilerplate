from manager_behavior import build_manager_profiles


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

