Exit code: 0
Wall time: 1 seconds
Output:
from analysis_engine import build_external_indexes, build_league_analysis, enrich_player


CONTEXT = {"sources": {
    "ktc": {"data": [{"name": "Carnell Tate", "value": 5975, "rank": 36,
                       "positional_rank": 12, "tier": 8}]},
    "offensive_lines": {"data": [{"team": "TEN", "overall_rank": 28}]},
    "weeks_1_13": {"data": [{"team": "TEN", "WR": 6}]},
    "weeks_1_17": {"data": [{"team": "TEN", "WR": 3}]},
}}


def test_player_evaluation_contains_every_required_context():
    player = {"player_id": "1", "name": "Carnell Tate", "position": "WR",
              "team": "TEN", "roster_slot": "starter"}
    result = enrich_player(player, build_external_indexes(CONTEXT))
    assert result["market"]["value"] == 5975
    assert result["offensive_line"]["data"]["overall_rank"] == 28
    assert result["strength_of_schedule"]["weeks_1_13_rank"] == 6
    assert result["strength_of_schedule"]["weeks_1_17_rank"] == 3


def test_league_analysis_ranks_measured_value_without_fake_window_label():
    league = {"league_id": "x", "teams": [
        {"roster_id": 1, "players": [{"name": "Carnell Tate", "position": "WR",
          "team": "TEN", "roster_slot": "starter"}], "draft_picks": []},
        {"roster_id": 2, "players": [], "draft_picks": []},
    ]}
    result = build_league_analysis(league, CONTEXT)
    assert result["teams"][0]["analysis"]["league_relative"]["ktc_starter_value_rank"] == 1
    assert result["teams"][0]["analysis"]["competitive_window"]["classification"] == (
        "insufficient_projection_data"
    )

