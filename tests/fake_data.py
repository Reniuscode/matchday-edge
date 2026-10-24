"""Writes a synthetic cache so the pipeline and site can be tested without network access.

Usage: MDE_DATA=/tmp/mde python tests/fake_data.py && MDE_DATA=/tmp/mde python -m pipeline.build --offline
The numbers are random - never use this output for betting.
"""
import datetime as dt
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.config import fd_season_code, season_start_year  # noqa: E402

random.seed(7)
DATA = os.environ["MDE_DATA"]
CACHE = os.path.join(DATA, "cache")
os.makedirs(os.path.join(CACHE, "fd"), exist_ok=True)
os.makedirs(os.path.join(CACHE, "espn_players"), exist_ok=True)

TEAMS = [("Arsenal", "ARS", "e20520"), ("Aston Villa", "AVL", "660e43"), ("AFC Bournemouth", "BOU", "d71920"),
         ("Brentford", "BRE", "e30613"), ("Brighton & Hove Albion", "BHA", "0057b8"), ("Chelsea", "CHE", "034694"),
         ("Coventry City", "COV", "59cbe8"), ("Crystal Palace", "CRY", "1b458f"), ("Everton", "EVE", "003399"),
         ("Fulham", "FUL", "000000"), ("Hull City", "HUL", "f5a12d"), ("Ipswich Town", "IPS", "0044a9"),
         ("Leeds United", "LEE", "ffcd00"), ("Liverpool", "LIV", "c8102e"), ("Manchester City", "MNC", "6cabdd"),
         ("Manchester United", "MAN", "da291c"), ("Newcastle United", "NEW", "241f20"),
         ("Nottingham Forest", "NFO", "dd0000"), ("Sunderland", "SUN", "eb172b"), ("Tottenham Hotspur", "TOT", "132257")]
FD_NAMES = {"AFC Bournemouth": "Bournemouth", "Brighton & Hove Albion": "Brighton", "Coventry City": "Coventry",
            "Hull City": "Hull", "Ipswich Town": "Ipswich", "Leeds United": "Leeds", "Manchester City": "Man City",
            "Manchester United": "Man United", "Newcastle United": "Newcastle", "Nottingham Forest": "Nott'm Forest",
            "Tottenham Hotspur": "Tottenham"}
REFS = ["M Oliver", "A Taylor", "C Kavanagh", "S Hooper", "P Bankes", "J Gillett", "R Jones", "T Bramall",
        "D England", "S Attwell"]
strength = {t[0]: (random.uniform(0.7, 1.4), random.uniform(0.7, 1.3)) for t in TEAMS}
ref_strict = {r: random.uniform(0.8, 1.25) for r in REFS}
FIRST = ["J.", "M.", "L.", "A.", "B.", "C.", "D.", "K.", "R.", "S."]
LAST = ["Silva", "Smith", "Jones", "Rice", "Palmer", "Saka", "Rogers", "Neto", "Gray", "Kudus", "Tonali", "Isak",
        "Watkins", "Mbeumo", "Wissa", "Caicedo", "Fernandes", "Mount", "Ward", "Mitchell", "Hall", "Burn", "Lewis"]


def pois(lam):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= random.random()
        if p < L:
            return k
        k += 1


def odds3(ph, pd, pa, margin=1.05):
    return [round(1 / (p * margin), 2) for p in (ph, pd, pa)]


def season(year, n_rounds=38):
    names = [t[0] for t in TEAMS]
    rows = []
    start = dt.date(year, 8, 15)
    pairs = [(h, a) for h in names for a in names if h != a]
    random.shuffle(pairs)
    per_round = len(names) // 2
    for rnd in range(min(n_rounds, len(pairs) // per_round)):
        day = start + dt.timedelta(days=7 * rnd)
        used, fixtures = set(), []
        for h, a in pairs:
            if h in used or a in used:
                continue
            fixtures.append((h, a))
            used |= {h, a}
            if len(fixtures) == per_round:
                break
        for f in fixtures:
            pairs.remove(f)
        for h, a in fixtures:
            lh = 1.45 * strength[h][0] / strength[a][1]
            la = 1.15 * strength[a][0] / strength[h][1]
            ref = random.choice(REFS)
            hg, ag = pois(lh), pois(la)
            ph = min(0.8, 0.45 * lh / (lh + la) * 2)
            pd = 0.25
            pa = max(0.05, 1 - ph - pd)
            o = odds3(ph, pd, pa)
            ov = round(1 / (0.55 * 1.05), 2)
            un = round(1 / (0.45 * 1.05), 2)
            rows.append({
                "kickoff": f"{day.isoformat()}T15:00", "home": FD_NAMES.get(h, h), "away": FD_NAMES.get(a, a),
                "referee": ref, "hg": hg, "ag": ag, "hxg": round(lh * random.uniform(.8, 1.2), 2),
                "axg": round(la * random.uniform(.8, 1.2), 2), "hs": pois(13 * strength[h][0]),
                "as": pois(11 * strength[a][0]), "hst": pois(4.6 * strength[h][0]), "ast": pois(3.9 * strength[a][0]),
                "hf": pois(10.5), "af": pois(11), "hc": pois(5.4 * strength[h][0]), "ac": pois(4.5 * strength[a][0]),
                "hy": pois(1.9 * ref_strict[ref]), "ay": pois(2.1 * ref_strict[ref]), "hr": int(random.random() < .05),
                "ar": int(random.random() < .06),
                "odds": {"1x2": {"books": {"Bet365": dict(zip(("home", "draw", "away"), o)),
                                           "Betfair Exchange": dict(zip(("home", "draw", "away"), [x * 1.04 for x in o]))},
                                 "max": None, "avg": dict(zip(("home", "draw", "away"), o))},
                         "ou25": {"books": {"Bet365": {"over": ov, "under": un}}, "max": None,
                                  "avg": {"over": ov, "under": un}}},
                "closing": {},
            })
    return rows


sy = season_start_year()
today = dt.date.today()
for y in range(sy - 4, sy + 1):
    rows = season(y, 38 if y < sy else 9)
    if y == sy:
        rows = [r for r in rows if r["kickoff"][:10] < today.isoformat()]
    with open(os.path.join(CACHE, "fd", f"E0_{fd_season_code(y)}.json"), "w") as f:
        json.dump(rows, f)

cur = json.load(open(os.path.join(CACHE, "fd", f"E0_{fd_season_code(sy)}.json")))
info = {t[0]: {"espn_id": str(300 + i), "name": t[0], "short": t[0].split(" ")[0], "abbr": t[1], "color": t[2],
               "alt_color": "ffffff", "logo": None} for i, t in enumerate(TEAMS)}
inv = {v: k for k, v in FD_NAMES.items()}
events, athletes = [], {}
squads = {}
pid = 1000
for t in TEAMS:
    sq = []
    for pos in ["G"] + ["D"] * 6 + ["M"] * 6 + ["F"] * 4:
        pid += 1
        nm = f"{random.choice(FIRST)} {random.choice(LAST)}"
        sq.append({"id": str(pid), "pos": pos, "name": nm.replace(".", "") + "son", "short": nm,
                   "shr": random.uniform(.3, 2.0) * {"G": 0, "D": .4, "M": 1, "F": 1.8}[pos],
                   "fr": random.uniform(.4, 2.2), "wr": random.uniform(.3, 2.5)})
    squads[t[0]] = sq
for i, m in enumerate(cur):
    h, a = inv.get(m["home"], m["home"]), inv.get(m["away"], m["away"])
    eid = str(500000 + i)
    events.append({"espn_id": eid, "kickoff": m["kickoff"] + ":00Z", "state": "post", "completed": True,
                   "status": "FT", "home": info[h], "away": info[a], "score": [m["hg"], m["ag"]], "venue": "Stadium"})
    lines = {}
    for side, team in (("home", h), ("away", a)):
        sq = squads[team]
        chosen = [sq[0]] + random.sample(sq[1:7], 4) + random.sample(sq[7:13], 4) + random.sample(sq[13:], 2)
        subs = random.sample([p for p in sq if p not in chosen and p["pos"] != "G"], 3)
        out = []
        for p in chosen + subs:
            mins = 90 if p in chosen else random.choice([10, 20, 30])
            if p in chosen[-3:]:
                mins = random.choice([60, 70, 80, 90])
            sh = pois(p["shr"] * mins / 90)
            out.append({"id": p["id"], "name": p["name"], "short": p["short"], "pos": p["pos"], "min": mins,
                        "start": 1.0 if p in chosen else 0.0, "sh": sh, "sot": sum(random.random() < .35 for _ in range(sh)),
                        "g": int(random.random() < .1 * p["shr"]), "a": int(random.random() < .07),
                        "fc": pois(p["fr"] * mins / 90), "fw": pois(p["wr"] * mins / 90),
                        "yc": int(random.random() < .12), "rc": 0, "xg": round(.1 * sh, 2)})
        lines[side] = out
    json.dump(lines, open(os.path.join(CACHE, "espn_players", eid + ".json"), "w"))

# upcoming round
names = [t[0] for t in TEAMS]
random.shuffle(names)
nxt = today + dt.timedelta(days=1)
fixtures = []
for k in range(10):
    h, a = names[2 * k], names[2 * k + 1]
    ko = dt.datetime.combine(nxt + dt.timedelta(days=k // 4), dt.time(12 + (k % 4) * 2, 30))
    events.append({"espn_id": str(600000 + k), "kickoff": ko.isoformat() + "Z", "state": "pre", "completed": False,
                   "status": "Scheduled", "home": info[h], "away": info[a], "score": [None, None], "venue": "Stadium"})
    o = [round(random.uniform(1.4, 4.5), 2), round(random.uniform(3.2, 4.2), 2), round(random.uniform(1.6, 6), 2)]
    fixtures.append({"kickoff": ko.isoformat()[:16], "home": FD_NAMES.get(h, h), "away": FD_NAMES.get(a, a),
                     "referee": random.choice(REFS),
                     "odds": {"1x2": {"books": {"Bet365": dict(zip(("home", "draw", "away"), o)),
                                                "Sky Bet": dict(zip(("home", "draw", "away"), [x * 1.03 for x in o]))},
                                      "max": None, "avg": dict(zip(("home", "draw", "away"), o))},
                              "ou25": {"books": {"Bet365": {"over": 1.9, "under": 1.95}}, "max": None,
                                       "avg": {"over": 1.9, "under": 1.95}}}})
json.dump(fixtures, open(os.path.join(CACHE, "fd", "fixtures.json"), "w"))
json.dump(events, open(os.path.join(CACHE, "espn_events.json"), "w"))
print(f"fake data in {DATA}: {len(events)} events")
