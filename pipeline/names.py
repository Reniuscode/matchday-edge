"""Matching team and player names across football-data, ESPN and FPL."""
from __future__ import annotations

import difflib
import re
import unicodedata

# football-data.co.uk / FPL short names -> ESPN display names
TEAM_ALIASES = {
    "man city": "manchester city",
    "man united": "manchester united",
    "man utd": "manchester united",
    "nott'm forest": "nottingham forest",
    "nottm forest": "nottingham forest",
    "spurs": "tottenham hotspur",
    "tottenham": "tottenham hotspur",
    "wolves": "wolverhampton wanderers",
    "west ham": "west ham united",
    "newcastle": "newcastle united",
    "brighton": "brighton & hove albion",
    "bournemouth": "afc bournemouth",
    "leeds": "leeds united",
    "hull": "hull city",
    "ipswich": "ipswich town",
    "coventry": "coventry city",
    "leicester": "leicester city",
    "sheffield united": "sheffield united",
    "sheffield utd": "sheffield united",
    "sheff utd": "sheffield united",
    "sheffield weds": "sheffield wednesday",
    "west brom": "west bromwich albion",
    "norwich": "norwich city",
    "luton": "luton town",
    "stoke": "stoke city",
    "cardiff": "cardiff city",
    "swansea": "swansea city",
    "qpr": "queens park rangers",
    "derby": "derby county",
    "birmingham": "birmingham city",
    "oxford": "oxford united",
    "preston": "preston north end",
    "plymouth": "plymouth argyle",
    "charlton": "charlton athletic",
    "blackburn": "blackburn rovers",
    "bristol city": "bristol city",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str) -> str:
    s = strip_accents(s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def team_key(name: str) -> str:
    n = norm(name)
    n = TEAM_ALIASES.get(n, n)
    n = n.replace(" fc", "").replace("afc ", "").replace("&", "and")
    return re.sub(r"[^a-z0-9]", "", n)


class TeamMatcher:
    """Maps any source's team name onto a canonical list (ESPN names)."""

    def __init__(self, canonical_names):
        self.by_key = {team_key(n): n for n in canonical_names}

    def match(self, name: str) -> str | None:
        k = team_key(name)
        if k in self.by_key:
            return self.by_key[k]
        close = difflib.get_close_matches(k, list(self.by_key), n=1, cutoff=0.72)
        return self.by_key[close[0]] if close else None


def player_tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-z]+", norm(name)) if t]


def player_similarity(a: str, b: str) -> float:
    """Loose score for 'Moisés Caicedo' vs 'Caicedo' vs 'M. Caicedo'."""
    ta, tb = player_tokens(a), player_tokens(b)
    if not ta or not tb:
        return 0.0
    if ta[-1] == tb[-1]:
        return 0.9 if (ta[0][0] == tb[0][0] or len(ta) == 1 or len(tb) == 1) else 0.75
    sa, sb = set(ta), set(tb)
    if sa & sb:
        return 0.6 * len(sa & sb) / min(len(sa), len(sb))
    return difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio() * 0.6
