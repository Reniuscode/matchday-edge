"""Walk-forward backtest: for every past match, predict using only data known before kick-off.

Answers two questions honestly:
1. Calibration - when the model says 70%, does it happen ~70% of the time?
2. Value bets - would the flagged 1X2 / over-under 2.5 bets have made money at the posted prices?
"""
from __future__ import annotations

import math

from .config import season_label
from .model import expected_counts, goal_markets, league_baseline, p_over, referee_profile, team_rows, team_strength
from .pricing import effective, market_fair, price_market

MIN_GAMES = 2
BUCKETS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]


def _outcomes(m):
    hg, ag = m["hg"], m["ag"]
    out = {"home": hg > ag, "draw": hg == ag, "away": hg < ag, "over_2.5": hg + ag > 2.5,
           "under_2.5": hg + ag < 2.5, "btts_yes": hg > 0 and ag > 0, "1X": hg >= ag, "X2": ag >= hg,
           "over_1.5": hg + ag > 1.5, "under_3.5": hg + ag < 3.5}
    if m.get("hc") is not None:
        c = m["hc"] + m["ac"]
        out.update({"corners_over_8.5": c > 8.5, "corners_over_9.5": c > 9.5, "corners_under_10.5": c < 10.5})
    if m.get("hy") is not None:
        k = m["hy"] + m["ay"] + (m.get("hr") or 0) + (m.get("ar") or 0)
        out.update({"cards_over_2.5": k > 2.5, "cards_over_3.5": k > 3.5, "cards_under_4.5": k < 4.5})
    return out


def run_backtest(seasons: dict, current_start: int, n_seasons: int = 3) -> dict:
    years = [y for y in sorted(seasons) if y > current_start - n_seasons and seasons[y]]
    calib = {b: [0, 0.0, 0] for b in BUCKETS}  # n, sum p, hits
    by_group: dict = {}
    bets = []
    ll = {"model": 0.0, "market": 0.0, "blend": 0.0, "n": 0}
    for y in years:
        cur = sorted(seasons[y], key=lambda m: m["kickoff"])
        prev = seasons.get(y - 1, [])
        refs_hist = [m for yy in seasons if yy < y for m in seasons[yy]]
        base_cache: dict = {}
        prev_base = league_baseline(prev) if prev else None
        prev_teams = {t for m in prev for t in (m["home"], m["away"])}
        prior = {t: team_rows(prev, t) for t in prev_teams}
        for i, m in enumerate(cur):
            before = cur[:i]
            hr, ar = team_rows(before, m["home"]), team_rows(before, m["away"])
            if len(hr) < MIN_GAMES or len(ar) < MIN_GAMES:
                continue
            day = m["kickoff"][:10]
            if day not in base_cache:  # same-day matches share one baseline
                base_cache.clear()
                base_cache[day] = league_baseline(before + prev if len(before) < 100 else before)
            base = base_cache[day]
            if not base.get("goals") or not base.get("cards"):
                continue
            hs = team_strength(hr, base, prior.get(m["home"]), prev_base, promoted=bool(prev) and m["home"] not in prev_teams)
            as_ = team_strength(ar, base, prior.get(m["away"]), prev_base, promoted=bool(prev) and m["away"] not in prev_teams)
            ref = referee_profile(refs_hist + before, m.get("referee"), base)
            exp = expected_counts(hs, as_, base, ref)
            gm = goal_markets(*exp["goals"])
            probs = {k: gm[k] for k in ("home", "draw", "away", "over_2.5", "under_2.5", "btts_yes", "1X", "X2",
                                        "over_1.5", "under_3.5")}
            if "corners" in exp:
                c = sum(exp["corners"])
                ph = base["corners"]["phi"]
                probs.update({"corners_over_8.5": p_over(8.5, c, ph), "corners_over_9.5": p_over(9.5, c, ph),
                              "corners_under_10.5": 1 - p_over(10.5, c, ph)})
            if "cards" in exp:
                k = sum(exp["cards"])
                ph = base["cards"]["phi"]
                probs.update({"cards_over_2.5": p_over(2.5, k, ph), "cards_over_3.5": p_over(3.5, k, ph),
                              "cards_under_4.5": 1 - p_over(4.5, k, ph)})
            res = _outcomes(m)
            for key, p in probs.items():
                if key not in res:
                    continue
                hit = res[key]
                for b in BUCKETS:
                    if b[0] <= p < b[1] or (b[1] == 1.0 and p >= 1.0):
                        c = calib[b]
                        c[0] += 1
                        c[1] += p
                        c[2] += hit
                group = key.split("_")[0] if key.startswith(("corners", "cards")) else "goals/result"
                g = by_group.setdefault(group, [0, 0.0])
                g[0] += 1
                g[1] += (p - hit) ** 2

            # value bets at the pre-match prices
            o = m.get("odds") or {}
            odds = {"1x2": (o.get("1x2") or {}).get("books", {}), "ou25": (o.get("ou25") or {}).get("books", {}),
                    "avg": {"1x2": (o.get("1x2") or {}).get("avg"), "ou25": (o.get("ou25") or {}).get("avg")}}
            fair = market_fair(odds, "1x2")
            if fair:
                won = "home" if res["home"] else ("draw" if res["draw"] else "away")
                bl = {k: 0.5 * probs[k] + 0.5 * fair[k] for k in fair}
                ll["model"] -= math.log(max(1e-9, probs[won]))
                ll["market"] -= math.log(max(1e-9, fair[won]))
                ll["blend"] -= math.log(max(1e-9, bl[won]))
                ll["n"] += 1
            for kind, side, key in (("1x2", "home", "home"), ("1x2", "draw", "draw"), ("1x2", "away", "away"),
                                    ("ou25", "over", "over_2.5"), ("ou25", "under", "under_2.5")):
                pm = price_market(key, "", "", probs[key], odds, (kind, side))
                if pm.get("value"):
                    win = res[key]
                    price = effective(pm["best_book"], pm["best"])
                    bets.append({"date": m["kickoff"][:10], "match": f"{m['home']} v {m['away']}", "pick": key,
                                 "price": pm["best"], "book": pm["best_book"], "edge": pm["edge"],
                                 "won": bool(win), "profit": round(price - 1 if win else -1, 3)})
    bets.sort(key=lambda b: b["date"])
    total = sum(b["profit"] for b in bets)
    curve, run = [], 0.0
    for b in bets:
        run += b["profit"]
        curve.append([b["date"], round(run, 2)])
    by_pick: dict = {}
    for b in bets:
        k = "Result" if b["pick"] in ("home", "draw", "away") else "Goals O/U 2.5"
        s = by_pick.setdefault(k, {"bets": 0, "won": 0, "profit": 0.0})
        s["bets"] += 1
        s["won"] += b["won"]
        s["profit"] += b["profit"]
    for s in by_pick.values():
        s["roi"] = round(s["profit"] / s["bets"], 4) if s["bets"] else None
        s["profit"] = round(s["profit"], 2)
    n = ll["n"] or 1
    return {
        "seasons": [season_label(y) for y in years],
        "calibration": [{"range": f"{int(b[0]*100)}-{int(b[1]*100)}%", "n": c[0],
                         "predicted": round(c[1] / c[0], 3) if c[0] else None,
                         "actual": round(c[2] / c[0], 3) if c[0] else None} for b, c in calib.items()],
        "brier": {g: round(v[1] / v[0], 4) for g, v in by_group.items() if v[0]},
        "logloss_1x2": {"model": round(ll["model"] / n, 4), "market": round(ll["market"] / n, 4),
                        "blend": round(ll["blend"] / n, 4), "matches": ll["n"]},
        "bets": {"count": len(bets), "won": sum(b["won"] for b in bets), "profit": round(total, 2),
                 "roi": round(total / len(bets), 4) if bets else None, "by_market": by_pick,
                 "curve": curve[:: max(1, len(curve) // 150)] + (curve[-1:] if curve else []),
                 "recent": bets[-25:][::-1]},
    }
