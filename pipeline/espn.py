"""ESPN public JSON: fixtures, team branding, per-player match stats and Bet365 odds."""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
from fractions import Fraction

from .net import fetch_json, pmap

SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}"
CORE = "https://sports.core.api.espn.com/v2/sports/soccer/leagues/{slug}"

PLAYER_STATS = {
    # ESPN stat name -> our short key
    "minutes": "min", "starts": "start", "subIns": "subin",
    "totalShots": "sh", "shotsOnTarget": "sot", "totalGoals": "g", "goalAssists": "a",
    "foulsCommitted": "fc", "foulsSuffered": "fw", "yellowCards": "yc", "redCards": "rc",
    "expectedGoals": "xg", "offsides": "off", "totalTackles": "tkl", "saves": "sv",
}


def _team(c: dict) -> dict:
    t = c.get("team", {})
    logo = t.get("logo") or ((t.get("logos") or [{}])[0].get("href"))
    return {
        "espn_id": str(t.get("id")), "name": t.get("displayName") or t.get("name"),
        "short": t.get("shortDisplayName") or t.get("name"), "abbr": t.get("abbreviation"),
        "color": t.get("color"), "alt_color": t.get("alternateColor"), "logo": logo,
    }


def _event(e: dict) -> dict:
    comp = e["competitions"][0]
    teams = {c["homeAway"]: c for c in comp["competitors"]}
    st = e.get("status", {}).get("type", {})
    return {
        "espn_id": str(e["id"]), "kickoff": e["date"], "state": st.get("state"),
        "completed": bool(st.get("completed")), "status": st.get("shortDetail"),
        "home": _team(teams["home"]), "away": _team(teams["away"]),
        "score": [teams["home"].get("score"), teams["away"].get("score")],
        "venue": (comp.get("venue") or {}).get("fullName"),
        "stats": {side: _team_stats(teams[side]) for side in ("home", "away")},
    }


TEAM_STATS = {"foulsCommitted": "fouls", "wonCorners": "corners", "shotsOnTarget": "sot", "totalShots": "shots"}


def _team_stats(c: dict) -> dict:
    out = {}
    for s in c.get("statistics") or []:
        k = TEAM_STATS.get(s.get("name"))
        try:
            if k:
                out[k] = float(s.get("displayValue"))
        except (TypeError, ValueError):
            pass
    return out


def season_events(slug: str, start: dt.date, end: dt.date) -> list[dict]:
    """All league events between two dates. Tries one ranged call, then falls back to weekly chunks."""
    events = {}
    if True:  # ESPN refuses date-range queries from some networks, so ask one day at a time
        days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]

        def grab(day):
            try:
                return fetch_json(SITE.format(slug=slug) + f"/scoreboard?dates={day:%Y%m%d}").get("events", [])
            except Exception as ex:
                print(f"    {day}: {ex}")
                return []
        for evs in pmap(grab, days, workers=6):
            for e in evs:
                events[str(e["id"])] = _event(e)
    return sorted(events.values(), key=lambda e: e["kickoff"])


class AthleteCache:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        try:
            with open(path) as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    def get(self, ref: str, pid: str) -> dict:
        if pid in self.data:
            return self.data[pid]
        try:
            a = fetch_json(ref)
            pos = (a.get("position") or {}).get("abbreviation") or ""
            info = {"name": a.get("displayName") or a.get("fullName"),
                    "short": a.get("shortName") or a.get("displayName"), "pos": pos}
        except Exception:
            info = {"name": f"Player {pid}", "short": f"Player {pid}", "pos": ""}
        with self.lock:
            self.data[pid] = info
        return info

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f, separators=(",", ":"), sort_keys=True)


def _parse_stats(js: dict) -> dict:
    out = {}
    for cat in (js.get("splits") or {}).get("categories", []):
        for s in cat.get("stats", []):
            k = PLAYER_STATS.get(s.get("name"))
            if k and k not in out and s.get("value") is not None:
                out[k] = float(s["value"])
    return out


def event_player_lines(slug: str, event: dict, athletes: AthleteCache) -> dict | None:
    """Per-player stat lines for both teams of a completed event, or None if ESPN has none yet."""
    eid = event["espn_id"]
    base = CORE.format(slug=slug) + f"/events/{eid}/competitions/{eid}/competitors"
    out = {}
    for side in ("home", "away"):
        tid = event[side]["espn_id"]
        try:
            roster = fetch_json(f"{base}/{tid}/roster?lang=en&region=us")
        except Exception:
            return None
        entries = [en for en in roster.get("entries", [])
                   if en.get("starter") or (en.get("subbedIn") or {}).get("didSub")]
        if not entries:
            return None

        def one(en):
            pid = str(en.get("playerId"))
            ref = (en.get("statistics") or {}).get("$ref")
            stats = {}
            if ref:
                try:
                    stats = _parse_stats(fetch_json(ref))
                except Exception:
                    stats = {}
            ath = athletes.get((en.get("athlete") or {}).get("$ref", ""), pid)
            if "min" not in stats:  # derive minutes from substitution clocks if needed
                start = 0 if en.get("starter") else _clock((en.get("subbedIn") or {}).get("clock"))
                end = _clock((en.get("subbedOut") or {}).get("clock")) if (en.get("subbedOut") or {}).get("didSub") else 90
                stats["min"] = max(0, (end or 90) - (start or 0))
            stats["start"] = 1.0 if en.get("starter") else 0.0
            return {"id": pid, "name": ath["name"], "short": ath["short"], "pos": ath["pos"] or "",
                    "jersey": en.get("jersey"), **stats}

        out[side] = [p for p in pmap(one, entries, workers=6) if p.get("min", 0) > 0]
    return out


def _clock(c):
    if not c:
        return None
    v = c.get("value")
    return round(v / 60) if v is not None else None


def _frac_to_dec(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        s = str(v)
        if "/" in s:
            return round(float(Fraction(s)) + 1, 3)
        f = float(s)
        return f if f > 1 else None
    except Exception:
        return None


def bet365_odds(slug: str, event_id: str) -> dict | None:
    """Bet365 prices ESPN embeds in its match summary (1X2, double chance, goal line)."""
    try:
        js = fetch_json(SITE.format(slug=slug) + f"/summary?event={event_id}")
    except Exception:
        return None
    for o in js.get("odds") or []:
        if not o or "365" not in ((o.get("provider") or {}).get("name") or ""):
            continue
        t = ((o.get("bettingOdds") or {}).get("teamOdds")) or {}
        val = lambda k: _frac_to_dec((t.get(k) or {}).get("value"))  # noqa: E731
        res = {
            "1x2": {"home": val("preMatchFullTimeResultHome"), "draw": val("preMatchFullTimeResultDraw"),
                    "away": val("preMatchFullTimeResultAway")},
            "dc": {"1X": val("preMatchDoubleChanceHomeOrDraw"), "X2": val("preMatchDoubleChanceDrawOrAway"),
                   "12": val("preMatchDoubleChanceHomeOrAway")},
        }
        line = (t.get("preMatchOverUnderHandicap") or {}).get("value")
        try:
            line = float(line)
        except Exception:
            line = None
        if line is not None:
            res["goal_line"] = {"line": line, "over": val("preMatchGoalLineOver"), "under": val("preMatchGoalLineUnder")}
        if not any(res["1x2"].values()) and not any(res["dc"].values()):
            return None
        return res
    return None


def load_event_cache(cache_dir: str, eid: str):
    p = os.path.join(cache_dir, f"{eid}.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return None


def save_event_cache(cache_dir: str, eid: str, data):
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, f"{eid}.json"), "w") as f:
        json.dump(data, f, separators=(",", ":"))
