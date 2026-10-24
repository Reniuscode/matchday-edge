# Matchday Edge

Premier League stats sheets, model probabilities, value bets and an acca builder, built entirely from free data.

**Site:** https://reniuscode.github.io/matchday-edge/

## What it does

- **Match sheets** for every upcoming fixture: team averages and last-5 form (goals, xG, shots, shots on target, corners, fouls, cards, saves), match hit rates, the referee's card and foul record, and player tables for shots, shots on target, fouls committed and won, cards and goals. Player tables show season hit rates and a model probability for this match.
- **Value bets**: compares the model's probability with bookmaker prices (Bet365, Betfair Exchange, Sky Bet, Paddy Power and others) and flags prices that beat it.
- **Player props: price to beat**: there is no free odds feed for player props, so the site shows the fair price for each and the odds you'd need to call it value.
- **Acca builder**: generates banker, bigger-price and value accas (one leg per match) from your filters, and adds them to a bet slip that works out the combined chance and expected return.
- **Track record**: a walk-forward backtest of the last three seasons. It checks calibration and how the flagged value bets would have done.

## How it runs

A GitHub Actions workflow (`.github/workflows/update.yml`) runs every 4 hours. It:

1. runs `python -m pipeline.build`, which uses only the standard library and caches finished matches in `data/cache/`,
2. commits `data/` back to the repo,
3. publishes `site/` plus `data/latest.json` to GitHub Pages.

Run it by hand from **Actions → Update data and publish site → Run workflow**.

## Data sources (all free)

| Source | Used for |
| --- | --- |
| football-data.co.uk | Team match stats, xG, referees, bookmaker odds (results and upcoming fixtures) |
| ESPN public API | Fixtures, crests, per-player match stats (minutes, shots, SoT, fouls, cards, goals), Bet365 double-chance odds |
| Fantasy Premier League API | Injury and suspension news |
| The Odds API (optional) | Extra UK bookmaker prices. Add a free key as the repo secret `ODDS_API_KEY` (500 credits a month; this uses about 180) |

## Local development

```bash
python -m pipeline.build                 # live data -> data/latest.json
mkdir -p site/data && cp data/latest.json site/data/
python -m http.server -d site 8000       # open http://localhost:8000
```

Offline testing with random synthetic data (never bet on this):

```bash
MDE_DATA=/tmp/mde python tests/fake_data.py
MDE_DATA=/tmp/mde python -m pipeline.build --offline
python -m unittest discover tests
```

## Responsible gambling

18+. These are estimates, not certainties, and bookmakers build a margin into every price. Set limits and never chase losses. Help: [BeGambleAware](https://www.begambleaware.org), National Gambling Helpline 0808 8020 133, [GAMSTOP](https://www.gamstop.co.uk).
