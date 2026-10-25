"""Daily suggested bets: saved before kick-off, settled after full time.

Each UK match day gets three suggestions, built the same way as the site's defaults:
  - banker acca: the safest leg (70-90%) from each match, up to 4 legs
  - value acca: up to 3 flagged value bets from different matches
  - value singles: every flagged value bet that day
A day's picks keep updating with fresh odds and team news until its first game kicks off,
then they are frozen. After full time each leg is settled from ESPN match and player stats.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")
BANKER_MIN, BANKER_MAX, BANKER_LEGS = 0.70, 0.90, 4
BANKER_GROUPS = {"Result", "Goals", "Corners", "Players"}
PLAYER_LABELS = {
    "sh1": "1+ shots", "sh2": "2+ shots", "sot1": "1+ shots on target", "sot2": "2+ shots on target",
    "fc1": "1+ fouls committed", "fc2": "2+ fouls committed", "fw1": "1+ fouls won", "fw2": "2+ fouls won",
    "card": "to be carded", "goal": "anytime goalscorer",
}


def _ts(iso: str) -> dt.datetime:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))


def uk_day(iso: str) -> str:
    return _ts(iso).astimezone(UK).date().isoformat()


def _label(text: str, fx: dict) -> str:
    return text.replace("{home}", fx["home"].get("short") or fx["home"]["name"]).replace(
        "{away}", fx["away"].get("short") or fx["away"]["name"])


def fixture_legs(fx: dict) -> list[dict]:
    match = f"{fx['home'].get('short') or fx['home']['name']} v {fx['away'].get('short') or fx['away']['name']}"
    legs = []
    for m in fx["markets"]:
        legs.append({"fx": fx["id"], "match": match, "kickoff": fx["kickoff"], "market": m["id"], "group": m["group"],
                     "label": _label(m["label"], fx), "p": m.get("blended_p") or m["p"], "odds": m.get("best"),
                     "book": m.get("best_book"), "edge": m.get("edge"), "value": m.get("value")})
    for side in ("home", "away"):
        for pl in fx["players"][side]:
            if pl["exp_min"] < 60 or pl["pos"] == "G":
                continue
            for k, mk in pl["markets"].items():
                if mk["hit_n"] < 4 or mk["hit"] < 0.55:
                    continue
                legs.append({"fx": fx["id"], "match": match, "kickoff": fx["kickoff"], "market": f"p{pl['id']}:{k}",
                             "group": "Players", "label": f"{pl['short']} {PLAYER_LABELS[k]}", "p": mk["p"],
                             "odds": None, "book": None, "edge": None, "value": None, "player": pl["name"]})
    return legs


def _type(leg: dict) -> str:
    m = leg["market"]
    if m.startswith("p"):
        return m.split(":")[1]
    return re.sub(r"_?[\d.]+$", "", re.sub(r"^(home|away)_", "", m))


def pick_per_match(pool: list[dict], score, n: int) -> list[dict]:
    ranked = sorted((l for l in pool if score(l) is not None), key=score, reverse=True)
    used, types, out = set(), {}, []
    for l in ranked:
        t = _type(l)
        if l["fx"] in used or types.get(t, 0) >= 2:
            continue
        used.add(l["fx"])
        types[t] = types.get(t, 0) + 1
        out.append(l)
        if len(out) >= n:
            break
    return out


def day_suggestions(fixtures: list[dict]) -> dict:
    legs = [l for fx in fixtures for l in fixture_legs(fx)]
    banker_pool = [l for l in legs if l["group"] in BANKER_GROUPS and BANKER_MIN <= l["p"] <= BANKER_MAX
                   and not re.search(r"over_0\.5$|^under_0", l["market"])]
    banker = pick_per_match(banker_pool, lambda l: l["p"], BANKER_LEGS)
    value = [l for l in legs if l["value"] and l["p"] >= 0.3]
    value_acca = pick_per_match(value, lambda l: l["edge"], 3)
    out = {"singles": sorted(value, key=lambda l: -l["edge"])}
    if len(banker) >= 2:
        out["banker"] = banker
    if len(value_acca) >= 2:
        out["value_acca"] = value_acca
    return out


# ------------------------------------------------------------------ settling

KEY_STAT = {"sh1": ("sh", 1), "sh2": ("sh", 2), "sot1": ("sot", 1), "sot2": ("sot", 2), "fc1": ("fc", 1),
            "fc2": ("fc", 2), "fw1": ("fw", 1), "fw2": ("fw", 2), "card": ("card", 1), "goal": ("g", 1)}

def _totals(event: dict, lines: dict | None) -> dict:
    """Per-team counts for a finished match: goals from the score, other stats from ESPN."""
    t = {}
    for i, side in enumerate(("home", "away")):
        st = (event.get("stats") or {}).get(side, {})
        g = event["score"][i]
        t[side] = {"goals": float(g) if g not in (None, "") else None, **st}
        if lines and lines.get(side):
            t[side]["cards"] = sum((p.get("yc") or 0) + (p.get("rc") or 0) for p in lines[side])
    return t


def settle_leg(leg: dict, event: dict | None, lines: dict | None) -> str | None:
    """'won', 'lost', 'void' or None (not finished / not enough data yet)."""
    if not event or not event.get("completed"):
        return None
    m = leg["market"]
    if m.startswith("p"):
        if not lines:
            return None
        pid, key = m[1:].split(":")
        line = next((p for side in ("home", "away") for p in lines.get(side, []) if str(p["id"]) == pid), None)
        if not line or line.get("min", 0) <= 0:
            return "void"  # player didn't play: bookmakers void the bet
        stat, need = KEY_STAT[key]
        val = (line.get("yc") or 0) + (line.get("rc") or 0) if stat == "card" else (line.get(stat) or 0)
        return "won" if val >= need else "lost"
    t = _totals(event, lines)
    hg, ag = t["home"]["goals"], t["away"]["goals"]
    if hg is None or ag is None:
        return None
    simple = {"home": hg > ag, "draw": hg == ag, "away": hg < ag, "1X": hg >= ag, "X2": ag >= hg, "12": hg != ag,
              "btts_yes": hg > 0 and ag > 0, "btts_no": not (hg > 0 and ag > 0)}
    if m in simple:
        return "won" if simple[m] else "lost"
    mt = re.match(r"^(?:(home|away)_)?(?:(corners|cards|shots|sot|fouls)_)?(over|under)_([\d.]+)$", m)
    if not mt:
        return None
    side, stat, direction, line = mt.groups()
    stat = stat or "goals"
    vals = [t[s].get(stat) for s in ((side,) if side else ("home", "away"))]
    if any(v is None for v in vals):
        return None
    total = sum(vals)
    ok = total > float(line) if direction == "over" else total < float(line)
    return "won" if ok else "lost"


def _bet_result(legs: list[dict]) -> dict:
    states = [l.get("result") for l in legs]
    if any(s is None for s in states):
        status = "lost" if "lost" in states else "pending"
    else:
        live = [l for l in legs if l["result"] != "void"]
        status = "void" if not live else ("won" if all(l["result"] == "won" for l in live) else "lost")
    live = [l for l in legs if l.get("result") != "void"]
    odds = None
    if live and all(l.get("odds") for l in live):
        odds = 1.0
        for l in live:
            odds *= l["odds"]
    p = 1.0
    for l in live:
        p *= l["p"]
    profit = None
    if status in ("won", "lost", "void") and odds:
        profit = round(odds - 1, 2) if status == "won" else (0.0 if status == "void" else -1.0)
    return {"status": status, "odds": round(odds, 2) if odds else None, "p": round(p, 4), "profit": profit}


def update(path: str, fixtures: list[dict], events: list[dict], lines_for, backfill=None) -> dict:
    """Refresh today's/future suggestions, settle finished legs, return the history for the site."""
    try:
        with open(path) as f:
            hist = json.load(f)
    except (OSError, ValueError):
        hist = {"started": dt.date.today().isoformat(), "days": {}}
    now = dt.datetime.now(dt.timezone.utc)
    by_event = {e["espn_id"]: e for e in events}

    # 1. (re)build suggestions for days whose first game hasn't kicked off
    by_day: dict = {}
    for fx in fixtures:
        by_day.setdefault(uk_day(fx["kickoff"]), []).append(fx)
    for day, fxs in by_day.items():
        all_day = [e for e in events if uk_day(e["kickoff"]) == day]
        first = min(_ts(e["kickoff"]) for e in all_day) if all_day else min(_ts(f["kickoff"]) for f in fxs)
        if now >= first:
            continue  # frozen once the day's first game kicks off (and never invented after the fact)
        sug = day_suggestions(fxs)
        hist["days"][day] = {"frozen_at": first.isoformat(), "updated": now.isoformat(timespec="minutes"),
                             "matches": len(fxs), **{k: {"legs": v} for k, v in sug.items() if k != "singles"},
                             "singles": [{"legs": [l]} for l in sug["singles"]]}

    # 1b. past days we never saw live: re-create them with the model as it stood before that day
    if backfill:
        for day in sorted({uk_day(e["kickoff"]) for e in events if e["completed"]}):
            day_events = [e for e in events if uk_day(e["kickoff"]) == day]
            if day in hist["days"] or not all(e["completed"] for e in day_events):
                continue
            sug = day_suggestions(backfill(day))
            hist["days"][day] = {"simulated": True, "matches": len(day_events),
                                 **{k: {"legs": v} for k, v in sug.items() if k != "singles"},
                                 "singles": [{"legs": [l]} for l in sug["singles"]]}

    # 2. settle
    for day in hist["days"].values():
        bets = [day[k] for k in ("banker", "value_acca") if k in day] + day.get("singles", [])
        for bet in bets:
            for leg in bet["legs"]:
                if leg.get("result") in ("won", "lost", "void"):
                    continue
                ev = by_event.get(leg["fx"])
                leg["result"] = settle_leg(leg, ev, lines_for(leg["fx"]) if ev and ev.get("completed") else None)
            bet.update(_bet_result(bet["legs"]))

    with open(path, "w") as f:
        json.dump(hist, f, separators=(",", ":"))
    return summarise(hist)


def summarise(hist: dict) -> dict:
    def agg(bets):
        done = [b for b in bets if b["status"] in ("won", "lost")]
        priced = [b for b in done if b.get("profit") is not None]
        legs = [l for b in bets for l in b["legs"] if l.get("result") in ("won", "lost")]
        return {
            "bets": len(done), "won": sum(b["status"] == "won" for b in done),
            "pending": sum(b["status"] == "pending" for b in bets),
            "expected_wins": round(sum(b["p"] for b in done), 2),
            "legs": len(legs), "legs_won": sum(l["result"] == "won" for l in legs),
            "legs_expected": round(sum(l["p"] for l in legs), 2),
            "priced": len(priced), "profit": round(sum(b["profit"] for b in priced), 2),
            "roi": round(sum(b["profit"] for b in priced) / len(priced), 4) if priced else None,
        }

    days = hist["days"]
    return {
        "started": hist.get("started"),
        "summary": {
            "banker": agg([d["banker"] for d in days.values() if "banker" in d]),
            "value_acca": agg([d["value_acca"] for d in days.values() if "value_acca" in d]),
            "singles": agg([s for d in days.values() for s in d.get("singles", [])]),
        },
        "days": [{"date": k, **v} for k, v in sorted(days.items(), reverse=True)][:60],
        "live_summary": {
            "banker": agg([d["banker"] for d in days.values() if "banker" in d and not d.get("simulated")]),
            "value_acca": agg([d["value_acca"] for d in days.values() if "value_acca" in d and not d.get("simulated")]),
            "singles": agg([s for d in days.values() if not d.get("simulated") for s in d.get("singles", [])]),
        },
    }
