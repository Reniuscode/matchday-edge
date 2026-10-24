"""League and season settings. Add more leagues here later (same two sources cover them)."""
from __future__ import annotations

import datetime as dt

LEAGUES = {
    "EPL": {
        "name": "Premier League",
        "fd_code": "E0",        # football-data.co.uk division code
        "espn_slug": "eng.1",   # ESPN league slug
        "fpl": True,            # FPL injury news only exists for the Premier League
        "odds_api_key": "soccer_epl",
    },
}


def season_start_year(today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    return today.year if today.month >= 7 else today.year - 1


def fd_season_code(start_year: int) -> str:
    """2026 -> '2627' (football-data.co.uk folder naming)."""
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def season_label(start_year: int) -> str:
    return f"{start_year}/{(start_year + 1) % 100:02d}"
