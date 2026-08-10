Exit code: 0
Wall time: 1.2 seconds
Output:
from external_sources import parse_ktc, parse_offensive_lines, parse_sos


def test_parse_ktc_embedded_public_array():
    html = '''<script>var playersArray = [{"playerName":"A","position":"WR",
    "team":"TEN","age":21.0,"superflexValues":{"value":6000,"rank":10,
    "positionalRank":4,"overallTier":3},"oneQBValues":{"value":5000}}];</script>'''
    assert parse_ktc(html)[0]["value"] == 6000


def test_parse_offensive_line_table():
    html = """<table><tr><th>Team</th><th>Proj Run Grade</th><th>Run Rank</th>
    <th>Proj Pass Grade</th><th>Pass Rank</th><th>Overall Grade</th>
    <th>Overall Rank</th></tr><tr><td>TEN</td><td>70.2</td><td>4</td>
    <td>65.1</td><td>8</td><td>68.0</td><td>6</td></tr></table>"""
    assert parse_offensive_lines(html)[0]["overall_rank"] == 6


def test_parse_sos_table():
    html = """<table><tr><th>TEAM</th><th>QB</th><th>RB</th><th>WR</th><th>TE</th>
    </tr><tr><td>TEN</td><td>2</td><td>8</td><td>3</td><td>6</td></tr></table>"""
    assert parse_sos(html)[0] == {"team": "TEN", "QB": 2, "RB": 8, "WR": 3, "TE": 6}

