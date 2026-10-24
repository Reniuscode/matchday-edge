"""Optional extras: FPL injury news (Premier League only) and The Odds API (needs a free key)."""
from __future__ import annotations

import json
import os
import time

from .names import TeamMatcher, player_similarity
from .net import fetch_json

FPL_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
STATUS = {"a": "available", "d": "doubtful", "i": "injured", "s": "suspended", "u": "unavailable", "n": "unavailable"}


def fpl_availability(team_names: list[str]) -> dict:
    """{espn team name: [{name, web, status, chance, news}]}; empty dict if FPL is unreachable."""
    try:
        js = fetch_json(FPL_URL)
    except Exception as e:
        print(f"  FPL unavailable: {e}")
        return {}
    matcher = TeamMatcher(team_names)
    team_by_id = {t["id"]: matcher.match(t["name"]) for t in js.get("teams", [])}
    out: dict[str, list] = {}
    for p in js.get("elements", []):
        team = team_by_id.get(p.get("team"))
        if not team:
            continue
        out.setdefault(team, []).append({
            "name": f"{p.get('first_name', '')} {p.get('second_name', '')}".strip(),
            "web": p.get("web_name"), "status": STATUS.get(p.get("status"), "available"),
            "chance": p.get("chance_of_playing_next_round"), "news": p.get("news") or "",
        })
    return out


def match_fpl(player_name: str, candidates: list[dict]) -> dict | None:
    best, score = None, 0.0
    for c in candidates:
        s = max(player_similarity(player_name, c["name"]), player_similarity(player_name, c["web"] or ""))
        if s > score:
            best, score = c, s
    return best if score >= 0.75 else None


def odds_api(sport_key: str, cache_path: str, max_age_h: float = 11.5) -> list:
    """Best UK prices for 1X2 and totals. Uses ~2 credits per call; cached so the free 500/month lasts."""
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        return []
    try:
        if time.time() - os.path.getmtime(cache_path) < max_age_h * 3600:
            with open(cache_path) as f:
                return json.load(f)
    except OSError:
        pass
    url = (f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds?regions=uk&markets=h2h,totals"
           f"&oddsFormat=decimal&apiKey={key}")
    try:
        data = fetch_json(url)
    except Exception as e:
        print(f"  Odds API failed: {e}")
        try:
            with open(cache_path) as f:
                return json.load(f)
        except OSError:
            return []
    with open(cache_path, "w") as f:
        json.dump(data, f)
    return data


def odds_api_for(events: list, home: str, away: str, matcher: TeamMatcher) -> dict | None:
    """Reshape one Odds API event into our odds block."""
    for ev in events:
        if matcher.match(ev.get("home_team", "")) != home or matcher.match(ev.get("away_team", "")) != away:
            continue
        x12: dict = {}
        totals: dict = {}
        for bk in ev.get("bookmakers", []):
            for m in bk.get("markets", []):
                if m["key"] == "h2h":
                    o = {}
                    for oc in m["outcomes"]:
                        side = "draw" if oc["name"] == "Draw" else ("home" if matcher.match(oc["name"]) == home else "away")
                        o[side] = oc["price"]
                    if len(o) == 3:
                        x12[bk["title"]] = o
                elif m["key"] == "totals":
                    o = {}
                    for oc in m["outcomes"]:
                        if oc.get("point") == 2.5:
                            o[oc["name"].lower()] = oc["price"]
                    if len(o) == 2:
                        totals[bk["title"]] = o
        return {"1x2": x12, "ou25": totals}
    return None
