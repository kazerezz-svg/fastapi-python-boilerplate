# Sleeper Dynasty Intelligence

FastAPI service for league 1337530303182290944 that combines live Sleeper
state, linked-season transaction history, KeepTradeCut market benchmarks,
4for4 offensive-line projections, and FFToolbox positional strength of
schedule.

## Capabilities

- Live rosters, starters, bench, taxi, reserve, managers, and traded picks
- Historical transactions across Sleeper's previous_league_id chain
- KTC, offensive-line, and Weeks 1-13/1-17 SOS context for every player
- League-relative roster and lineup analysis
- Historical manager trade tendencies
- Bounded trade-package generation and player recommendations
- Scheduled JSON snapshots for persistent analysis

## Important endpoints

- /league-map - normalized current league
- /history - linked-season completed transactions
- /external-context - KTC, 4for4, and SOS with freshness/status
- /analysis/league - enriched league-relative analysis
- /analysis/player/{sleeper_player_id} - complete player context
- /manager-behavior - measured historical manager tendencies
- /trade-search/{sleeper_player_id} - ranked packages
- /recommendation/player/{sleeper_player_id} - direct offer guidance

Interactive OpenAPI documentation is available at /docs.

## Configuration

Copy .env.example to .env for local development.

| Variable | Required | Purpose |
| --- | --- | --- |
| SLEEPER_LEAGUE_ID | No | Defaults to the configured league |
| SLEEPER_USER_ID | No | Defaults to the configured manager |
| PROJECTIONS_URL | No | Authorized JSON projection feed |
| API_BASE_URL | For snapshots | Deployed API URL used by GitHub Actions |

Projection JSON may be a list or an object with a players list. Each row accepts
player_id (preferred), name, and projected_points. Competitive-window
classification remains unavailable until at least 70% of starters match.

## Local development

~~~powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e . --group dev
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\uvicorn main:app --reload
~~~

## Snapshots

scripts/refresh_snapshot.py fetches the league, history, and external context
and atomically writes snapshots/latest.json. The refresh-snapshot.yml workflow
runs every six hours after the repository secret API_BASE_URL is configured.

## Methodology boundaries

- KTC is a crowdsourced market benchmark, not a projection or decision rule.
- Pick values use a labeled neutral-mid benchmark when quality is unknown.
- Manager tendencies are descriptive and receive only a limited score adjustment.
- Lineup impact currently uses optimized KTC market value.
- Every sourced or heuristic field is labeled in API responses.

