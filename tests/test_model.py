import unittest

from pipeline.model import goal_markets, nb_pmf, p_over, poisson_pmf
from pipeline.names import TeamMatcher, player_similarity
from pipeline.pricing import devig, price_market


class ModelTests(unittest.TestCase):
    def test_distributions_sum_to_one(self):
        self.assertAlmostEqual(sum(poisson_pmf(k, 2.7) for k in range(60)), 1, places=6)
        self.assertAlmostEqual(sum(nb_pmf(k, 10.3, 1.4) for k in range(200)), 1, places=6)

    def test_nb_wider_than_poisson(self):
        self.assertGreater(p_over(14.5, 10, 1.5), p_over(14.5, 10, 1.0))

    def test_goal_markets_consistent(self):
        g = goal_markets(1.6, 1.1)
        self.assertAlmostEqual(g["home"] + g["draw"] + g["away"], 1, places=6)
        self.assertGreater(g["home"], g["away"])
        self.assertAlmostEqual(g["over_2.5"] + g["under_2.5"], 1, places=6)

    def test_devig_and_value(self):
        f = devig({"home": 2.0, "draw": 3.6, "away": 4.0}, ("home", "draw", "away"))
        self.assertAlmostEqual(sum(f.values()), 1)
        odds = {"1x2": {"Bet365": {"home": 2.5, "draw": 3.4, "away": 3.0}}}
        m = price_market("home", "Result", "", 0.48, odds, ("1x2", "home"))
        self.assertEqual(m["best"], 2.5)
        self.assertIsNotNone(m["value"])
        self.assertIsNone(price_market("home", "Result", "", 0.30, odds, ("1x2", "home"))["value"])


class NameTests(unittest.TestCase):
    def test_team_aliases(self):
        m = TeamMatcher(["Nottingham Forest", "Manchester United", "Tottenham Hotspur", "Brighton & Hove Albion", "AFC Bournemouth"])
        self.assertEqual(m.match("Nott'm Forest"), "Nottingham Forest")
        self.assertEqual(m.match("Man United"), "Manchester United")
        self.assertEqual(m.match("Spurs"), "Tottenham Hotspur")
        self.assertEqual(m.match("Brighton"), "Brighton & Hove Albion")
        self.assertEqual(m.match("Bournemouth"), "AFC Bournemouth")

    def test_player_similarity(self):
        self.assertGreaterEqual(player_similarity("Moisés Caicedo", "Caicedo"), 0.75)
        self.assertLess(player_similarity("Mason Mount", "Martin Odegaard"), 0.75)


if __name__ == "__main__":
    unittest.main()


class NoFalseMatchTests(unittest.TestCase):
    def test_relegated_team_not_matched_to_other(self):
        m = TeamMatcher(["Manchester City", "Leeds United"])
        self.assertIsNone(m.match("Leicester"))
