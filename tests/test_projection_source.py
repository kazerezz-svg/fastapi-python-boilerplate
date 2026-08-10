from projection_source import parse_adp_table, parse_draft_sharks, parse_projection_table


def test_parses_projection_points():
    html = '<table><tbody><tr><td><a>Player One</a> BUF</td><td>10</td><td>301.5</td></tr></tbody></table>'
    assert parse_projection_table(html, "qb")[0] == {
        "name": "Player One", "position": "QB", "projected_points": 301.5,
    }


def test_parses_redraft_adp_average():
    html = '<table><thead><tr><th>Rank</th><th>Player</th><th>POS</th><th>AVG</th><th>RT</th></tr></thead><tbody><tr><td>1</td><td><a>Player One</a></td><td>RB1</td><td>2.5</td><td>1</td></tr></tbody></table>'
    assert parse_adp_table(html)[0]["redraft_adp"] == 2.5


def test_parses_draft_sharks_redraft_value_and_projection_range():
    html = '''<table><thead><tr><th>RK</th><th>Player</th><th>Games</th><th>ADP</th><th>Bye</th><th>SOS</th><th>Injury Risk</th><th>Floor Proj</th><th>Consensus Proj</th><th>DS Proj</th><th>Ceiling Proj</th><th>3D Value</th></tr></thead><tbody><tr><td>1</td><td><a>Player One</a> BUF WR1</td><td>17</td><td>2.05</td><td>7</td><td>1%</td><td>20%</td><td>180</td><td>220</td><td>230</td><td>270</td><td>95</td></tr></tbody></table>'''
    row = parse_draft_sharks(html)[0]
    assert row["redraft_adp"] == 17
    assert row["projected_points"] == 230
    assert row["redraft_value"] == 95
