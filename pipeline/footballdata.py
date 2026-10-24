"""football-data.co.uk: team match stats, referees and bookmaker odds (free CSVs)."""
from __future__ import annotations

import csv
import datetime as dt
import io

from .net import fetch_text

BASE = "https://www.football-data.co.uk"


def _num(v):
    if v is None:
        return None
    v = str(v).strip()
    if v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _date(d: str, t: str | None) -> str:
    d = d.strip()
    fmt = "%d/%m/%Y" if len(d.split("/")[-1]) == 4 else "%d/%m/%y"
    day = dt.datetime.strptime(d, fmt).date()
    return f"{day.isoformat()}T{(t or '15:00').strip() or '15:00'}"


def parse_csv(text: str, div: str | None = None) -> list[dict]:
    rows = []
    reader = csv.DictReader(io.StringIO(text))
    for r in reader:
        if not r.get("Div") or not r.get("HomeTeam"):
            continue
        if div and r["Div"].strip() != div:
            continue
        rows.append(r)
    return rows


def odds_from_row(r: dict) -> dict:
    """Pre-match odds block. Keys mirror bookmaker names for display."""
    def trio(prefix):
        h, d, a = _num(r.get(prefix + "H")), _num(r.get(prefix + "D")), _num(r.get(prefix + "A"))
        return {"home": h, "draw": d, "away": a} if h and d and a else None

    def ou(prefix):
        o, u = _num(r.get(prefix + ">2.5")), _num(r.get(prefix + "<2.5"))
        return {"over": o, "under": u} if o and u else None

    books = {
        "Bet365": "B365", "Betfair Exchange": "BFE", "Betfred": "BFD", "BetVictor": "BV",
        "bwin": "BW", "Paddy Power": "PP", "Sky Bet": "SKB", "William Hill": "WH",
    }
    result = {name: trio(p) for name, p in books.items() if trio(p)}
    totals = {name: ou(p) for name, p in {"Bet365": "B365", "Betfair Exchange": "BFE"}.items() if ou(p)}
    out = {
        "1x2": {"books": result, "max": trio("Max"), "avg": trio("Avg")},
        "ou25": {"books": totals, "max": ou("Max"), "avg": ou("Avg")},
    }
    ah = _num(r.get("AHh"))
    if ah is not None:
        out["ah"] = {"line": ah, "b365": [_num(r.get("B365AHH")), _num(r.get("B365AHA"))],
                     "max": [_num(r.get("MaxAHH")), _num(r.get("MaxAHA"))],
                     "avg": [_num(r.get("AvgAHH")), _num(r.get("AvgAHA"))]}
    return out


def closing_odds_from_row(r: dict) -> dict:
    def trio(prefix):
        h, d, a = _num(r.get(prefix + "CH")), _num(r.get(prefix + "CD")), _num(r.get(prefix + "CA"))
        return {"home": h, "draw": d, "away": a} if h and d and a else None

    def ou(prefix):
        o, u = _num(r.get(prefix + "C>2.5")), _num(r.get(prefix + "C<2.5"))
        return {"over": o, "under": u} if o and u else None

    return {"1x2": {"max": trio("Max"), "avg": trio("Avg"), "b365": trio("B365")},
            "ou25": {"max": ou("Max"), "avg": ou("Avg"), "b365": ou("B365")}}


def result_row(r: dict) -> dict | None:
    """One completed match with the stats the sheets use."""
    hg, ag = _num(r.get("FTHG")), _num(r.get("FTAG"))
    if hg is None or ag is None:
        return None
    g = lambda k: _num(r.get(k))  # noqa: E731
    return {
        "kickoff": _date(r["Date"], r.get("Time")),
        "home": r["HomeTeam"].strip(), "away": r["AwayTeam"].strip(),
        "referee": (r.get("Referee") or "").strip() or None,
        "hg": hg, "ag": ag, "hxg": g("HxG"), "axg": g("AxG"),
        "hs": g("HS"), "as": g("AS"), "hst": g("HST"), "ast": g("AST"),
        "hf": g("HF"), "af": g("AF"), "hc": g("HC"), "ac": g("AC"),
        "hy": g("HY"), "ay": g("AY"), "hr": g("HR"), "ar": g("AR"),
        "odds": odds_from_row(r), "closing": closing_odds_from_row(r),
    }


def fixture_row(r: dict) -> dict:
    return {
        "kickoff": _date(r["Date"], r.get("Time")),
        "home": r["HomeTeam"].strip(), "away": r["AwayTeam"].strip(),
        "referee": (r.get("Referee") or "").strip() or None,
        "odds": odds_from_row(r),
    }


def load_season(code: str, div: str) -> list[dict]:
    text = fetch_text(f"{BASE}/mmz4281/{code}/{div}.csv")
    return [m for m in (result_row(r) for r in parse_csv(text, div)) if m]


def load_fixtures(div: str) -> list[dict]:
    text = fetch_text(f"{BASE}/fixtures.csv")
    return [fixture_row(r) for r in parse_csv(text, div)]
