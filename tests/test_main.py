Exit code: 0
Wall time: 1.2 seconds
Output:
from main import build_pick_ownership, estimate_pick_quality


def test_pick_ownership_uses_explicit_seasons_and_rounds():
    managers = {
        1: {"username": "one", "team_name": "One"},
        2: {"username": "two", "team_name": "Two"},
    }
    traded = [{"season": "2028", "round": 1, "roster_id": 2, "owner_id": 1}]

    picks = build_pick_ownership(
        target_roster_id=1,
        traded_picks=traded,
        roster_to_manager=managers,
        num_teams=2,
        seasons=[2028],
        draft_rounds=2,
    )

    assert len(picks) == 3
    assert any(p["original_roster_id"] == 2 and p["round"] == 1 for p in picks)
    assert not any(p["original_roster_id"] == 2 and p["round"] == 2 for p in picks)


def test_pick_quality_does_not_infer_from_age_preseason():
    team = {
        "standings": {"wins": 0, "losses": 0, "points_for": 0},
        "roster_profile": {"overall": {"average_age": 31.0}},
    }
    assert estimate_pick_quality(team) == "unknown"


def test_pick_quality_uses_measured_record_in_season():
    assert estimate_pick_quality({"standings": {"wins": 7, "losses": 2}}) == "late"
    assert estimate_pick_quality({"standings": {"wins": 2, "losses": 7}}) == "early"

