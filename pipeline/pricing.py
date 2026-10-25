"""Turning probabilities into fair odds and comparing them with bookmaker prices."""
from __future__ import annotations

from statistics import median

EXCHANGE_COMMISSION = 0.05   # Betfair Exchange takes ~5% of winnings, so its price is worth a bit less
MODEL_WEIGHT = 0.5           # how much we trust our model vs the market's own (de-vigged) view
MIN_BLENDED_EDGE = 0.04      # flag as value only above this...
MIN_MODEL_EDGE = 0.05        # ...and when the raw model edge is clearly positive too
# Only flag markets where the backtest held up. Over/under 2.5 edges lost ~7% over three seasons,
# so they are shown but never flagged. Re-check with `python -m pipeline.tune` each season.
FLAG_KINDS = {"1x2", "dc"}

SETS = {"1x2": ("home", "draw", "away"), "ou25": ("over", "under")}


def effective(book: str, price: float) -> float:
    if "exchange" in book.lower():
        return 1 + (price - 1) * (1 - EXCHANGE_COMMISSION)
    return price


def devig(prices: dict, keys) -> dict | None:
    if not prices or any(not prices.get(k) for k in keys):
        return None
    inv = {k: 1 / prices[k] for k in keys}
    s = sum(inv.values())
    return {k: v / s for k, v in inv.items()}


def market_fair(odds: dict, kind: str) -> dict | None:
    """Bookmaker consensus probability with the margin removed (median across books)."""
    if kind == "dc":
        x = market_fair(odds, "1x2")
        if not x:
            return None
        return {"1X": x["home"] + x["draw"], "X2": x["away"] + x["draw"], "12": x["home"] + x["away"]}
    keys = SETS[kind]
    fairs = [f for f in (devig(p, keys) for p in (odds.get(kind) or {}).values()) if f]
    avg = devig((odds.get("avg") or {}).get(kind) or {}, keys)
    if avg:
        fairs.append(avg)
    if not fairs:
        return None
    return {k: median(f[k] for f in fairs) for k in keys}


def price_market(mid: str, group: str, label: str, p: float, odds: dict, olook) -> dict:
    p = max(0.0001, min(0.9999, p))
    m = {"id": mid, "group": group, "label": label, "p": round(p, 4), "fair": round(1 / p, 2)}
    if not olook:
        return m
    kind, side = olook
    prices = {book: v.get(side) for book, v in (odds.get(kind) or {}).items() if v and v.get(side)}
    if not prices:
        return m
    best_book = max(prices, key=lambda b: effective(b, prices[b]))
    best = prices[best_book]
    best_eff = effective(best_book, best)
    fair = market_fair(odds, kind)
    mp = fair.get(side) if fair else None
    blended = MODEL_WEIGHT * p + (1 - MODEL_WEIGHT) * mp if mp else p
    edge_model = p * best_eff - 1
    edge_blend = blended * best_eff - 1
    tier = None
    if kind in FLAG_KINDS and edge_blend >= MIN_BLENDED_EDGE and edge_model >= MIN_MODEL_EDGE:
        tier = "strong" if edge_blend >= 0.10 else ("good" if edge_blend >= 0.05 else "small")
    m.update({
        "odds": {b: round(v, 2) for b, v in sorted(prices.items(), key=lambda kv: -kv[1])},
        "best": round(best, 2), "best_book": best_book,
        "market_p": round(mp, 4) if mp else None, "blended_p": round(blended, 4),
        "edge": round(edge_blend, 4), "edge_model": round(edge_model, 4), "value": tier,
    })
    return m
