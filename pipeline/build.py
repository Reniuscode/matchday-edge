"""Builds data/latest.json for the website.

Run:  python -m pipeline.build            (live data)
      python -m pipeline.build --offline  (re-use cached files only)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from statistics import mean

from . import espn, footballdata as fd
from .backtest import run_backtest
from .config import LEAGUES, fd_season_code, season_label, season_start_year
from .extras import fpl_availability, match_fpl, odds_api, odds_api_for
from .model import (PHI, PLAYER_MARKETS, avg, expected_counts, goal_markets, league_baseline, p_at_least, p_over,
                    player_priors, pos_group, referee_profile, team_rows, team_strength)
from .names import TeamMatcher
from .pricing import price_market

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("MDE_DATA") or os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "cache")

UPCOMING_DAYS = 8          # how far ahead past the next kickoff we show fixtures
HIT_MIN_MINUTES = 45       # player hit rates only count games with at least this many minutes


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------ loading


def load_fd_seasons(div: str, start_year: int, back: int = 4, offline: bool = False) -> dict[int, list[dict]]:
    out = {}
    for y in range(start_year - back, start_year + 1):
        code = fd_season_code(y)
        path = os.path.join(CACHE, "fd", f"{div}_{code}.json")
        try:
            if (y < start_year or offline) and os.path.exists(path):
                with open(path) as f:
                    out[y] = json.load(f)
                continue
            if offline:
                continue
            rows = fd.load_season(code, div)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(rows, f, separators=(",", ":"))
            out[y] = rows
            log(f"  football-data {code}: {len(rows)} matches")
        except Exception as e:
            log(f"  football-data {code} unavailable ({e})")
            if os.path.exists(path):
                with open(path) as f:
                    out[y] = json.load(f)
    return out


def rename(matches: list[dict], matcher: TeamMatcher) -> list[dict]:
    out = []
    for m in matches:
        h, a = matcher.match(m["home"]), matcher.match(m["away"])
        out.append({**m, "home": h or m["home"], "away": a or m["away"]})
    return out


# ------------------------------------------------------------------ team blocks

TEAM_STAT_KEYS = ["goals_for", "goals_against", "xg_for", "xg_against", "shots_for", "shots_against", "sot_for",
                  "sot_against", "corners_for", "corners_against", "fouls_for", "fouls_won", "cards_for",
                  "cards_against", "saves_for", "saves_against"]

HIT_RATES = [
    ("o25", "Over 2.5 goals", lambda r: r["goals_for"] + r["goals_against"] > 2.5),
    ("btts", "Both teams score", lambda r: r["goals_for"] > 0 and r["goals_against"] > 0),
    ("o95c", "Over 9.5 corners", lambda r: r["corners_for"] + r["corners_against"] > 9.5),
    ("o35k", "Over 3.5 cards", lambda r: r["cards_for"] + r["cards_against"] > 3.5),
    ("o205s", "Over 20.5 shots", lambda r: r["shots_for"] + r["shots_against"] > 20.5),
    ("o85t", "Over 8.5 shots on target", lambda r: r["sot_for"] + r["sot_against"] > 8.5),
]


def team_block(info: dict, rows: list[dict], table: dict) -> dict:
    last5 = rows[-5:]
    season = {k: _r(avg(rows, k)) for k in TEAM_STAT_KEYS}
    form = {k: [_r(r.get(k), 0) for r in last5] for k in TEAM_STAT_KEYS}
    l5avg = {k: _r(avg(last5, k)) for k in TEAM_STAT_KEYS}
    hits = {}
    for key, label, f in HIT_RATES:
        ok = []
        for r in rows:
            try:
                ok.append(bool(f(r)))
            except TypeError:
                ok.append(None)
        valid = [x for x in ok if x is not None]
        hits[key] = {"label": label, "season": _r(sum(valid) / len(valid), 3) if valid else None, "last5": ok[-5:]}
    return {
        **info, "played": len(rows), "table": table.get(info["name"]),
        "form": [{"r": r["result"], "score": f"{int(r['goals_for'])}-{int(r['goals_against'])}", "opp": r["opp"],
                  "venue": r["venue"], "date": r["kickoff"][:10]} for r in last5],
        "season": season, "last5_avg": l5avg, "last5": form, "hits": hits,
    }


def league_table(matches: list[dict]) -> dict:
    t: dict = {}
    for m in matches:
        for team, gf, ga in ((m["home"], m["hg"], m["ag"]), (m["away"], m["ag"], m["hg"])):
            s = t.setdefault(team, {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0})
            s["p"] += 1
            s["gf"] += gf
            s["ga"] += ga
            if gf > ga:
                s["w"] += 1
                s["pts"] += 3
            elif gf == ga:
                s["d"] += 1
                s["pts"] += 1
            else:
                s["l"] += 1
    order = sorted(t, key=lambda k: (-t[k]["pts"], -(t[k]["gf"] - t[k]["ga"]), -t[k]["gf"]))
    for i, k in enumerate(order):
        t[k]["pos"] = i + 1
        t[k]["gd"] = int(t[k]["gf"] - t[k]["ga"])
        t[k]["gf"], t[k]["ga"] = int(t[k]["gf"]), int(t[k]["ga"])
    return t


def _r(v, nd=2):
    return None if v is None else round(float(v), nd)


# ------------------------------------------------------------------ players


def player_table(team: str, apps: list[dict], team_events: list[str], priors: dict, opp_strength: dict,
                 venue_factors: dict, ref: dict | None, fpl: list[dict]) -> list[dict]:
    """apps: [{eid, kickoff, line}] for this team, oldest first."""
    by_player: dict = {}
    for a in apps:
        by_player.setdefault(a["line"]["id"], []).append(a)
    recent3 = set(team_events[-3:])
    recent5 = set(team_events[-5:])
    out = []
    for pid, games in by_player.items():
        games.sort(key=lambda g: g["kickoff"])
        lines = [g["line"] for g in games]
        last = lines[-1]
        played_recent = any(g["eid"] in recent5 for g in games)
        if not played_recent and len(games) < 3:
            continue
        group = pos_group(last.get("pos", ""))
        mins = sum(l.get("min", 0) for l in lines)
        tot = {k: sum((l.get(k) or 0) for l in lines) for k in ("g", "a", "sh", "sot", "fc", "fw", "yc", "rc", "xg")}
        tot["card"] = tot["yc"] + tot["rc"]
        for l in lines:
            l["card"] = (l.get("yc") or 0) + (l.get("rc") or 0)
        hit_lines = [l for l in lines if l.get("min", 0) >= HIT_MIN_MINUTES] or lines
        last5 = lines[-5:]
        exp_min = mean(l.get("min", 0) for l in last5)
        note = None
        if not any(g["eid"] in recent3 for g in games):
            exp_min *= 0.5
            note = "Not in the last 3 squads"
        avail = match_fpl(last["name"], fpl) if fpl else None
        status = "available"
        if avail:
            status = avail["status"]
            ch = avail["chance"]
            if status in ("injured", "suspended", "unavailable") and (ch is None or ch == 0):
                exp_min = 0
            elif ch is not None and ch < 100:
                exp_min *= ch / 100
            if avail["news"]:
                note = avail["news"]
        prior = priors.get(group, {})
        markets = {}
        for key, label, stat, n, opp_key, col in PLAYER_MARKETS:
            if group == "G":
                continue
            K = 3.0
            rate = (tot[stat] + prior.get(stat, 0) * K) / (mins / 90 + K)
            if stat == "g" and tot["xg"] > 0:  # blend in xG so one lucky finish does not dominate
                xrate = (tot["xg"] + prior.get("xg", 0) * K) / (mins / 90 + K)
                rate = 0.6 * xrate + 0.4 * rate
            if opp_key == "goal_def":
                opp = opp_strength["goal_def"]
            elif opp_key == "fouls_won":
                opp = opp_strength["fouls"][1]
            else:
                opp = opp_strength[opp_key][col]
            factor = opp * venue_factors.get(opp_key if opp_key in venue_factors else stat, 1.0)
            if stat == "card" and ref:
                factor *= ref["factor"]
            if stat == "fc" and ref:
                factor *= ref.get("fouls_factor", 1.0)
            lam = rate * exp_min / 90 * factor
            p = p_at_least(n, lam, PHI.get(stat, 1.0))
            hits = sum(1 for l in hit_lines if (l.get(stat) or 0) >= n)
            markets[key] = {"p": round(p, 4), "hit": round(hits / len(hit_lines), 3), "hit_n": len(hit_lines),
                            "lam": round(lam, 3)}
        out.append({
            "id": pid, "name": last["name"], "short": last.get("short") or last["name"], "pos": group,
            "apps": len(lines), "starts": int(sum(l.get("start", 0) for l in lines)), "mins": int(mins),
            "avg_min": round(mins / len(lines)), "exp_min": round(exp_min), "status": status, "note": note,
            "tot": {k: _r(v, 2) for k, v in tot.items()},
            "per_game": {k: _r(tot[k] / len(lines), 2) for k in ("sh", "sot", "fc", "fw", "card", "g", "a")},
            "per90": {k: _r(tot[k] / (mins / 90), 2) if mins else None for k in ("sh", "sot", "fc", "fw", "card", "g", "a")},
            "last5": {k: [int(l.get(k) or 0) for l in last5] for k in ("sh", "sot", "fc", "fw", "card", "g", "a", "min")},
            "markets": markets,
        })
    out.sort(key=lambda p: (-p["exp_min"], -p["mins"]))
    return out


# ------------------------------------------------------------------ main


def build(offline: bool = False, league_key: str = "EPL"):
    lg = LEAGUES[league_key]
    today = dt.date.today()
    sy = season_start_year(today)
    os.makedirs(os.path.join(CACHE, "fd"), exist_ok=True)
    log(f"Season {season_label(sy)} - {lg['name']}")

    seasons = load_fd_seasons(lg["fd_code"], sy, offline=offline)
    fx_path = os.path.join(CACHE, "fd", "fixtures.json")
    try:
        if offline:
            raise RuntimeError("offline")
        fixtures_fd = fd.load_fixtures(lg["fd_code"])
        with open(fx_path, "w") as f:
            json.dump(fixtures_fd, f, separators=(",", ":"))
    except Exception as e:
        log(f"  fixtures.csv not fetched ({e}); using cache")
        try:
            with open(fx_path) as f:
                fixtures_fd = json.load(f)
        except OSError:
            fixtures_fd = []
    log(f"  football-data fixtures: {len(fixtures_fd)}")

    ev_path = os.path.join(CACHE, "espn_events.json")
    if offline and os.path.exists(ev_path):
        with open(ev_path) as f:
            events = json.load(f)
    else:
        events = espn.season_events(lg["espn_slug"], dt.date(sy, 7, 25), today + dt.timedelta(days=21))
        with open(ev_path, "w") as f:
            json.dump(events, f, separators=(",", ":"))
    log(f"  ESPN events: {len(events)}")
    if not events:
        sys.exit("No ESPN events - aborting so the site keeps its last good data")

    teams_info = {}
    for e in events:
        for side in ("home", "away"):
            teams_info[e[side]["name"]] = e[side]
    matcher = TeamMatcher(list(teams_info))
    cur = sorted(rename(seasons.get(sy, []), matcher), key=lambda m: m["kickoff"])
    prev = rename(seasons.get(sy - 1, []), matcher)
    all_hist = [m for y in sorted(seasons) for m in rename(seasons[y], matcher)]

    # ---- player stats from ESPN (cached per finished match)
    athletes = espn.AthleteCache(os.path.join(CACHE, "athletes.json"))
    ev_cache = os.path.join(CACHE, "espn_players")
    done = [e for e in events if e["completed"]]
    missing = [e for e in done if espn.load_event_cache(ev_cache, e["espn_id"]) is None]
    log(f"  ESPN finished matches: {len(done)} ({len(missing)} need player stats)")
    if not offline:
        for i, e in enumerate(missing):
            try:
                lines = espn.event_player_lines(lg["espn_slug"], e, athletes)
            except Exception as ex:
                log(f"    {e['espn_id']} failed: {ex}")
                lines = None
            if lines:
                espn.save_event_cache(ev_cache, e["espn_id"], lines)
            if i % 10 == 9:
                log(f"    ...{i + 1}/{len(missing)}")
                athletes.save()
        athletes.save()

    team_apps: dict = {}
    team_events: dict = {}
    all_lines = []
    for e in done:
        lines = espn.load_event_cache(ev_cache, e["espn_id"])
        for side in ("home", "away"):
            name = e[side]["name"]
            team_events.setdefault(name, []).append(e["espn_id"])
            for l in (lines or {}).get(side, []):
                team_apps.setdefault(name, []).append({"eid": e["espn_id"], "kickoff": e["kickoff"], "line": l})
                all_lines.append(l)
    priors = player_priors(all_lines)

    # ---- baselines
    base_matches = cur if len(cur) >= 100 else cur + prev
    base = league_baseline(base_matches)
    table = league_table(cur)
    venue = {
        "home": {"shots": base["shots"]["home"], "sot": base["sot"]["home"], "goal_def": base["goals"]["home"],
                 "cards": base["cards"]["home"], "fouls": 1.0, "fouls_won": 1.0},
        "away": {"shots": base["shots"]["away"], "sot": base["sot"]["away"], "goal_def": base["goals"]["away"],
                 "cards": base["cards"]["away"], "fouls": 1.0, "fouls_won": 1.0},
    }

    fpl = fpl_availability(list(teams_info)) if (lg.get("fpl") and not offline) else {}
    oa_events = odds_api(lg["odds_api_key"], os.path.join(CACHE, "odds_api.json")) if not offline else []

    # ---- upcoming fixtures
    upcoming = [e for e in events if e["state"] == "pre"]
    if upcoming:
        first = dt.datetime.fromisoformat(upcoming[0]["kickoff"].replace("Z", "+00:00"))
        upcoming = [e for e in upcoming
                    if dt.datetime.fromisoformat(e["kickoff"].replace("Z", "+00:00")) <= first + dt.timedelta(days=UPCOMING_DAYS)]
    log(f"  Upcoming fixtures: {len(upcoming)}")

    fx_out = []
    for e in upcoming:
        home, away = e["home"]["name"], e["away"]["name"]
        fdrow = next((f for f in fixtures_fd if matcher.match(f["home"]) == home and matcher.match(f["away"]) == away), None)
        ref_name = fdrow["referee"] if fdrow else None
        hrows, arows = team_rows(cur, home), team_rows(cur, away)
        hs, as_ = team_strength(hrows, base), team_strength(arows, base)
        ref_cur = referee_profile(cur, ref_name, base)
        ref_all = referee_profile(all_hist, ref_name, base)
        ref_model = ref_all if ref_all and ref_all["games"] >= (ref_cur or {}).get("games", 0) else ref_cur
        exp = expected_counts(hs, as_, base, ref_model)
        gm = goal_markets(*exp["goals"])

        # odds from every source we have
        odds = {"1x2": {}, "ou25": {}, "dc": {}, "avg": {}}
        if fdrow:
            o = fdrow["odds"]
            odds["1x2"].update(o["1x2"]["books"])
            odds["ou25"].update(o["ou25"]["books"])
            odds["avg"] = {"1x2": o["1x2"]["avg"], "ou25": o["ou25"]["avg"]}
        if oa_events:
            oa = odds_api_for(oa_events, home, away, matcher)
            if oa:
                for k in ("1x2", "ou25"):
                    for b, v in oa[k].items():
                        odds[k].setdefault(b, v)
        b365 = None if offline else espn.bet365_odds(lg["espn_slug"], e["espn_id"])
        if b365:
            if all(b365["1x2"].values()):
                odds["1x2"].setdefault("Bet365", b365["1x2"])
            odds["dc"]["Bet365"] = b365["dc"]
            gl = b365.get("goal_line")
            if gl and gl["line"] == 2.5 and gl["over"] and gl["under"]:
                odds["ou25"].setdefault("Bet365", {"over": gl["over"], "under": gl["under"]})

        markets = build_markets(gm, exp, base, odds)
        h_info, a_info = teams_info[home], teams_info[away]
        players = {
            "home": player_table(home, team_apps.get(home, []), team_events.get(home, []), priors, as_, venue["home"],
                                 ref_model, fpl.get(home, [])),
            "away": player_table(away, team_apps.get(away, []), team_events.get(away, []), priors, hs, venue["away"],
                                 ref_model, fpl.get(away, [])),
        }
        fx_out.append({
            "id": e["espn_id"], "kickoff": e["kickoff"], "venue": e.get("venue"),
            "home": team_block(h_info, hrows, table), "away": team_block(a_info, arows, table),
            "referee": {"name": ref_name, "season": _ref_out(ref_cur), "career": _ref_out(ref_all)} if ref_name else None,
            "expected": {k: [_r(v[0]), _r(v[1])] for k, v in exp.items()},
            "top_scores": [{"score": s["score"], "p": _r(s["p"], 4)} for s in gm["top_scores"]],
            "markets": markets, "players": players,
            "has_odds": bool(odds["1x2"]),
        })
        log(f"    {home} v {away}: ref={ref_name or '-'} odds={len(odds['1x2'])} books")

    league_avgs = {k: {"mean": _r(v["mean"]), "home": _r(v["home"], 3), "phi": _r(v["phi"], 3)}
                   for k, v in base.items() if isinstance(v, dict)}
    log("  Backtesting...")
    bt = run_backtest({y: rename(seasons[y], matcher) for y in seasons}, sy)

    out = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "league": lg["name"], "season": season_label(sy), "matches_played": len(cur),
        "league_avgs": league_avgs, "table": table, "fixtures": fx_out, "backtest": bt,
        "sources": {"fd_fixtures": len(fixtures_fd), "espn_events": len(events), "player_matches": len(done) - len(missing) if offline else len(done),
                    "fpl": bool(fpl), "odds_api": bool(oa_events)},
    }
    with open(os.path.join(DATA, "latest.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"), allow_nan=False)
    log(f"Wrote data/latest.json with {len(fx_out)} fixtures")


def _ref_out(r):
    if not r:
        return None
    return {k: (_r(v, 2) if isinstance(v, float) else v) for k, v in r.items() if k != "name"}


MARKET_DEFS = [
    # id, group, label, prob key or callable, odds lookup
    ("home", "Result", "{home} to win", "home", ("1x2", "home")),
    ("draw", "Result", "Draw", "draw", ("1x2", "draw")),
    ("away", "Result", "{away} to win", "away", ("1x2", "away")),
    ("1X", "Result", "{home} or draw", "1X", ("dc", "1X")),
    ("X2", "Result", "{away} or draw", "X2", ("dc", "X2")),
    ("12", "Result", "Either team to win", "12", ("dc", "12")),
    ("over_1.5", "Goals", "Over 1.5 goals", "over_1.5", None),
    ("over_2.5", "Goals", "Over 2.5 goals", "over_2.5", ("ou25", "over")),
    ("under_2.5", "Goals", "Under 2.5 goals", "under_2.5", ("ou25", "under")),
    ("over_3.5", "Goals", "Over 3.5 goals", "over_3.5", None),
    ("under_3.5", "Goals", "Under 3.5 goals", "under_3.5", None),
    ("btts_yes", "Goals", "Both teams to score", "btts_yes", None),
    ("btts_no", "Goals", "Both teams to score: No", "btts_no", None),
    ("home_over_0.5", "Goals", "{home} to score", "home_over_0.5", None),
    ("away_over_0.5", "Goals", "{away} to score", "away_over_0.5", None),
    ("home_over_1.5", "Goals", "{home} over 1.5 goals", "home_over_1.5", None),
    ("away_over_1.5", "Goals", "{away} over 1.5 goals", "away_over_1.5", None),
]

COUNT_MARKETS = [
    # stat, group, total lines, team lines
    ("corners", "Corners", [7.5, 8.5, 9.5, 10.5, 11.5], [3.5, 4.5, 5.5]),
    ("cards", "Cards", [2.5, 3.5, 4.5, 5.5], [0.5, 1.5, 2.5]),
    ("shots", "Shots", [19.5, 22.5, 25.5], [9.5, 12.5]),
    ("sot", "Shots on target", [6.5, 7.5, 8.5, 9.5], [2.5, 3.5, 4.5]),
    ("fouls", "Fouls", [19.5, 21.5, 23.5], []),
]


def build_markets(gm: dict, exp: dict, base: dict, odds: dict) -> list[dict]:
    out = []
    for mid, group, label, pk, olook in MARKET_DEFS:
        p = gm[pk]
        out.append(price_market(mid, group, label, p, odds, olook))
    for stat, group, totals, team_lines in COUNT_MARKETS:
        if stat not in exp:
            continue
        h, a = exp[stat]
        phi = base[stat]["phi"]
        for line in totals:
            po = p_over(line, h + a, phi)
            out.append(price_market(f"{stat}_over_{line}", group, f"Over {line} {group.lower()}", po, odds, None))
            out.append(price_market(f"{stat}_under_{line}", group, f"Under {line} {group.lower()}", 1 - po, odds, None))
        team_phi = 1 + (phi - 1) * 0.7
        for line in team_lines:
            out.append(price_market(f"home_{stat}_over_{line}", group, "{home} over " + f"{line} {group.lower()}",
                                    p_over(line, h, team_phi), odds, None))
            out.append(price_market(f"away_{stat}_over_{line}", group, "{away} over " + f"{line} {group.lower()}",
                                    p_over(line, a, team_phi), odds, None))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    build(offline=ap.parse_args().offline)
