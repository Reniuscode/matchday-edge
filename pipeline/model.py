"""The prediction model.

Plain, explainable maths rather than a black box:
- Every count (goals, corners, cards, shots, fouls) gets an expected value from
  team-for x opponent-against strength vs the league average, shrunk towards
  average when there are few games, with a home-advantage factor.
- Goals use a Poisson score grid with a small Dixon-Coles low-score tweak.
- Other counts use a negative binomial whose spread is measured from the league.
- Referee and opponent adjust card and foul expectations.
"""
from __future__ import annotations

import math
from statistics import mean

# ---------------------------------------------------------------- distributions


def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


def nb_pmf(k: int, mu: float, phi: float) -> float:
    """Negative binomial with mean mu and variance phi*mu (phi<=1 falls back to Poisson)."""
    if phi <= 1.001 or mu <= 0:
        return poisson_pmf(k, mu)
    r = mu / (phi - 1)
    p = r / (r + mu)
    return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log(1 - p))


def p_at_least(n: int, mu: float, phi: float = 1.0) -> float:
    return max(0.0, min(1.0, 1 - sum(nb_pmf(k, mu, phi) for k in range(n))))


def p_over(line: float, mu: float, phi: float = 1.0) -> float:
    return p_at_least(int(math.floor(line)) + 1, mu, phi)


# ---------------------------------------------------------------- team records

STATS = {
    # key: (home column, away column)  -- from the team's own point of view
    "goals": ("hg", "ag"), "xg": ("hxg", "axg"), "shots": ("hs", "as"), "sot": ("hst", "ast"),
    "corners": ("hc", "ac"), "fouls": ("hf", "af"), "yellows": ("hy", "ay"), "reds": ("hr", "ar"),
}


def team_rows(matches: list[dict], team: str) -> list[dict]:
    """Per-match lines from one team's perspective, oldest first."""
    out = []
    for m in matches:
        if team not in (m["home"], m["away"]):
            continue
        home = m["home"] == team
        row = {"kickoff": m["kickoff"], "opp": m["away"] if home else m["home"], "venue": "H" if home else "A",
               "referee": m.get("referee")}
        for k, (hc, ac) in STATS.items():
            own, opp = (hc, ac) if home else (ac, hc)
            row[k + "_for"], row[k + "_against"] = m.get(own), m.get(opp)
        row["cards_for"] = _add(row["yellows_for"], row["reds_for"])
        row["cards_against"] = _add(row["yellows_against"], row["reds_against"])
        row["fouls_won"] = row["fouls_against"]  # fouls the opponent committed = fouls this team won
        row["saves_for"] = _sub(row["sot_against"], row["goals_against"])
        row["saves_against"] = _sub(row["sot_for"], row["goals_for"])
        gf, ga = row["goals_for"], row["goals_against"]
        row["result"] = "W" if gf > ga else ("D" if gf == ga else "L")
        out.append(row)
    return sorted(out, key=lambda r: r["kickoff"])


def _add(a, b):
    return None if a is None or b is None else a + b


def _sub(a, b):
    return None if a is None or b is None else max(0.0, a - b)


def avg(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return mean(vals) if vals else None


# ---------------------------------------------------------------- league baseline

TOTAL_KEYS = ["goals", "xg", "shots", "sot", "corners", "fouls", "cards"]


def league_baseline(matches: list[dict]) -> dict:
    """Per-team-per-game averages, home/away split factors and dispersion of match totals."""
    base: dict = {"n": len(matches)}
    for k, (hc, ac) in {**STATS, "cards": (None, None)}.items():
        if k == "cards":
            hv = [m["hy"] + m["hr"] for m in matches if m.get("hy") is not None and m.get("hr") is not None]
            av = [m["ay"] + m["ar"] for m in matches if m.get("ay") is not None and m.get("ar") is not None]
        else:
            hv = [m[hc] for m in matches if m.get(hc) is not None]
            av = [m[ac] for m in matches if m.get(ac) is not None]
        if not hv or not av:
            continue
        h, a = mean(hv), mean(av)
        overall = (h + a) / 2
        tot = [x + y for x, y in zip(hv, av)] if len(hv) == len(av) else []
        phi = 1.0
        if len(tot) > 20 and mean(tot) > 0:
            var = sum((t - mean(tot)) ** 2 for t in tot) / (len(tot) - 1)
            phi = max(1.0, min(1.8, var / mean(tot)))
        base[k] = {"mean": overall, "home": h / overall if overall else 1, "away": a / overall if overall else 1,
                   "phi": phi}
    return base


# Tunable settings (chosen with the walk-forward backtest, see pipeline/tune.py)
PARAMS = {
    "prior_games": 30.0,     # how many games' worth of weight last season's rating gets
    "regress": 0.65,         # how much of last season's edge carries over (rest regresses to average)
    "no_prior_games": 6.0,   # shrink-to-average weight when a team has no prior season
    "xg_weight": 0.5,        # goal ratings: share from xG vs actual goals
    "promoted_att": 0.85,    # promoted teams: assumed attack vs league average
    "promoted_def": 1.15,    # ...and defence (1.15 = concede 15% more)
}
ATTACKING = {"goals", "xg", "shots", "sot", "corners"}


def shrink(ratio: float | None, n: int, k: float = 6.0, target: float = 1.0) -> float:
    if ratio is None:
        return target
    w = n / (n + k)
    return target + (ratio - target) * w


def _raw_ratios(rows: list[dict], base: dict) -> dict:
    out = {}
    for k in ["goals", "xg", "shots", "sot", "corners", "fouls", "cards"]:
        lg = (base.get(k) or {}).get("mean")
        f, a = avg(rows, k + "_for"), avg(rows, k + "_against")
        out[k] = (f / lg if lg and f is not None else None, a / lg if lg and a is not None else None)
    return out


def team_strength(rows: list[dict], base: dict, prior_rows: list[dict] | None = None,
                  prior_base: dict | None = None, promoted: bool = False) -> dict:
    """Attack (for) and defence (against) ratios vs league average.

    Early in a season the ratings lean on last season (regressed to average); promoted teams
    start from a weaker prior. As games are played the current season takes over.
    """
    P = PARAMS
    n = len(rows)
    cur = _raw_ratios(rows, base)
    prev = _raw_ratios(prior_rows, prior_base or base) if prior_rows else None
    out = {"n": n}
    for k, (f, a) in cur.items():
        if prev and prev[k][0] is not None:
            tf = 1 + (prev[k][0] - 1) * P["regress"]
            ta = 1 + (prev[k][1] - 1) * P["regress"]
            kk = P["prior_games"]
        else:
            tf = P["promoted_att"] if (promoted and k in ATTACKING) else 1.0
            ta = P["promoted_def"] if (promoted and k in ATTACKING) else 1.0
            kk = P["no_prior_games"]
        out[k] = (shrink(f, n, kk, tf), shrink(a, n, kk, ta))
    w = P["xg_weight"]
    if base.get("xg") and cur["xg"][0] is not None:
        ga, gd = out["goals"]
        xa, xd = out["xg"]
        out["goal_att"], out["goal_def"] = w * xa + (1 - w) * ga, w * xd + (1 - w) * gd
    else:
        out["goal_att"], out["goal_def"] = out["goals"]
    return out


def referee_profile(matches: list[dict], ref: str | None, base: dict) -> dict | None:
    if not ref:
        return None
    games = [m for m in matches if m.get("referee") == ref and m.get("hy") is not None]
    if not games:
        return {"name": ref, "games": 0, "factor": 1.0, "fouls_factor": 1.0}
    yel = mean(m["hy"] + m["ay"] for m in games)
    red = mean((m.get("hr") or 0) + (m.get("ar") or 0) for m in games)
    fouls = [m["hf"] + m["af"] for m in games if m.get("hf") is not None]
    lg_cards = base["cards"]["mean"] * 2
    lg_fouls = base["fouls"]["mean"] * 2 if base.get("fouls") else None
    return {
        "name": ref, "games": len(games), "yellows": yel, "reds": red, "cards": yel + red,
        "fouls": mean(fouls) if fouls else None,
        "factor": shrink((yel + red) / lg_cards, len(games), k=8),
        "fouls_factor": shrink(mean(fouls) / lg_fouls, len(games), k=8) if fouls and lg_fouls else 1.0,
    }


# ---------------------------------------------------------------- match model


def expected_counts(hs: dict, as_: dict, base: dict, ref: dict | None) -> dict:
    """Expected per-team counts for this fixture."""
    exp = {}
    for k in ["shots", "sot", "corners", "fouls", "cards"]:
        b = base.get(k)
        if not b:
            continue
        h = b["mean"] * b["home"] * hs[k][0] * as_[k][1]
        a = b["mean"] * b["away"] * as_[k][0] * hs[k][1]
        if k == "cards" and ref:
            h, a = h * ref["factor"], a * ref["factor"]
        if k == "fouls" and ref:
            h, a = h * ref["fouls_factor"], a * ref["fouls_factor"]
        exp[k] = (h, a)
    g = base["goals"]
    exp["goals"] = (g["mean"] * g["home"] * hs["goal_att"] * as_["goal_def"],
                    g["mean"] * g["away"] * as_["goal_att"] * hs["goal_def"])
    return exp


def score_grid(lh: float, la: float, rho: float = -0.06, size: int = 11) -> list[list[float]]:
    grid = [[poisson_pmf(i, lh) * poisson_pmf(j, la) for j in range(size)] for i in range(size)]
    # Dixon-Coles tweak: real football has slightly more 0-0 / 1-1 than independent Poisson
    grid[0][0] *= 1 - lh * la * rho
    grid[0][1] *= 1 + lh * rho
    grid[1][0] *= 1 + la * rho
    grid[1][1] *= 1 - rho
    s = sum(map(sum, grid))
    return [[v / s for v in row] for row in grid]


def goal_markets(lh: float, la: float) -> dict:
    g = score_grid(lh, la)
    n = len(g)
    cells = [(i, j, g[i][j]) for i in range(n) for j in range(n)]
    P = lambda f: sum(p for i, j, p in cells if f(i, j))  # noqa: E731
    out = {
        "home": P(lambda i, j: i > j), "draw": P(lambda i, j: i == j), "away": P(lambda i, j: i < j),
        "btts_yes": P(lambda i, j: i > 0 and j > 0),
        "home_cs": P(lambda i, j: j == 0), "away_cs": P(lambda i, j: i == 0),
    }
    out["1X"], out["X2"], out["12"] = out["home"] + out["draw"], out["away"] + out["draw"], out["home"] + out["away"]
    out["btts_no"] = 1 - out["btts_yes"]
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        out[f"over_{line}"] = P(lambda i, j, L=line: i + j > L)
        out[f"under_{line}"] = 1 - out[f"over_{line}"]
    for line in (0.5, 1.5, 2.5):
        out[f"home_over_{line}"] = P(lambda i, j, L=line: i > L)
        out[f"away_over_{line}"] = P(lambda i, j, L=line: j > L)
    scores = sorted(cells, key=lambda c: -c[2])[:6]
    out["top_scores"] = [{"score": f"{i}-{j}", "p": p} for i, j, p in scores]
    return out


# ---------------------------------------------------------------- players

PLAYER_MARKETS = [
    # key, label, stat, threshold, opponent strength used, column of opponent (for=0/against=1)
    ("sh1", "1+ shots", "sh", 1, "shots", 1),
    ("sh2", "2+ shots", "sh", 2, "shots", 1),
    ("sot1", "1+ shots on target", "sot", 1, "sot", 1),
    ("sot2", "2+ shots on target", "sot", 2, "sot", 1),
    ("fc1", "1+ fouls committed", "fc", 1, "fouls_won", None),
    ("fc2", "2+ fouls committed", "fc", 2, "fouls_won", None),
    ("fw1", "1+ fouls won", "fw", 1, "fouls", 0),
    ("fw2", "2+ fouls won", "fw", 2, "fouls", 0),
    ("card", "To be carded", "card", 1, "cards", 1),
    ("goal", "Anytime goalscorer", "g", 1, "goal_def", None),
]

PHI = {"sh": 1.15, "sot": 1.05, "fc": 1.1, "fw": 1.1, "card": 1.0, "g": 1.0}


def pos_group(pos: str) -> str:
    p = (pos or "").upper()
    if p.startswith("G"):
        return "G"
    if p.startswith(("D", "CD", "LB", "RB", "CB", "WB", "SW")):
        return "D"
    if p.startswith(("F", "ST", "CF", "LW", "RW", "S")):
        return "F"
    return "M"


def player_priors(lines: list[dict]) -> dict:
    """League per-90 averages by position group, used to stabilise small samples."""
    acc: dict = {}
    for l in lines:
        g = pos_group(l.get("pos", ""))
        a = acc.setdefault(g, {"min": 0.0, "sh": 0.0, "sot": 0.0, "fc": 0.0, "fw": 0.0, "card": 0.0, "g": 0.0, "xg": 0.0})
        a["min"] += l.get("min", 0)
        for k in ("sh", "sot", "fc", "fw", "g", "xg"):
            a[k] += l.get(k, 0) or 0
        a["card"] += (l.get("yc", 0) or 0) + (l.get("rc", 0) or 0)
    return {g: {k: (v / (a["min"] / 90) if a["min"] else 0) for k, v in a.items() if k != "min"} for g, a in acc.items()}
