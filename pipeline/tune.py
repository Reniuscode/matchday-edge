"""Grid-search model settings on the cached football-data seasons (walk-forward, no peeking).

Run after a live build has filled data/cache/fd:  python -m pipeline.tune
"""
import itertools
import json
import os
import sys

from . import model, pricing
from .backtest import run_backtest
from .config import fd_season_code, season_start_year

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load():
    sy = season_start_year()
    seasons = {}
    for y in range(sy - 4, sy + 1):
        p = os.path.join(ROOT, "data", "cache", "fd", f"E0_{fd_season_code(y)}.json")
        if os.path.exists(p):
            seasons[y] = json.load(open(p))
    return seasons, sy


def score(seasons, sy):
    bt = run_backtest(seasons, sy, n_seasons=3)
    cal = sum(c["n"] * abs(c["predicted"] - c["actual"]) for c in bt["calibration"] if c["n"]) / max(1, sum(c["n"] for c in bt["calibration"]))
    return bt["logloss_1x2"]["model"], bt["logloss_1x2"]["market"], cal, bt["brier"], bt["bets"]


if __name__ == "__main__":
    seasons, sy = load()
    grid = {
        "prior_games": [6, 10, 16],
        "regress": [0.5, 0.7],
        "xg_weight": [0.5, 0.7, 0.85],
    }
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        grid = {k: [model.PARAMS[k]] for k in grid}
    rows = []
    for vals in itertools.product(*grid.values()):
        model.PARAMS.update(dict(zip(grid, vals)))
        ll, mk, cal, brier, bets = score(seasons, sy)
        rows.append((ll, vals, mk, cal, brier, bets["count"], bets["roi"]))
        print(f"{dict(zip(grid, vals))} logloss={ll} market={mk} calib_err={cal:.4f} brier={brier} bets={bets['count']} roi={bets['roi']}", flush=True)
    rows.sort()
    print("BEST", rows[0][:2])


def tune_pricing():
    """Which value rule would have held up? (Report only; beware over-fitting a few hundred bets.)"""
    seasons, sy = load()
    for w, edge, medge in itertools.product([0.25, 0.4, 0.5], [0.02, 0.04], [0.05, 0.10]):
        pricing.MODEL_WEIGHT, pricing.MIN_BLENDED_EDGE, pricing.MIN_MODEL_EDGE = w, edge, medge
        b = run_backtest(seasons, sy, n_seasons=3)["bets"]
        print(f"weight={w} blended>={edge} model>={medge}: bets={b['count']} roi={b['roi']} {b['by_market']}", flush=True)
