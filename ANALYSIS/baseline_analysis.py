"""
baseline_analysis.py
----------------
1. Parses a gameweek ("kupong") into 13 games with relevant features.
"""

import pandas as pd
import os


def parse_kupong(raw_input):
    """
    1. Splits a semicolon-separated kupong into 13 games
    2. For each game, splits into home, away, sv1, svx, sv2, o1, ox, and o2
    3. Replaces o1, ox, o2 with imp1, impx, imp2 as 1/odds & normalizing
    4. Makes sure all values are floats
    5. Returns a dataframe
    """

    rows = []
    games = [g.strip() for g in raw_input.split(";") if g.strip()]

    for i, game in enumerate(games, 1):

        game = game.lstrip().removeprefix(f"Game {i},").strip()

        parts = [p.strip() for p in game.split(", ")]
        if len(parts) != 8:
            raise ValueError(f"Game {i} does not have exactly 8 comma-space-separated values: {parts}")

        home, away, sv1, svx, sv2, o1, ox, o2 = parts

        sv_1, sv_x, sv_2 = map(float, (sv1, svx, sv2))
        o1 = float(o1.replace(",", "."))
        ox = float(ox.replace(",", "."))
        o2 = float(o2.replace(",", "."))

        # Convert decimal odds to implied probabilities (1/odds)
        imp_1 = 1 / o1
        imp_x = 1 / ox
        imp_2 = 1 / o2

        # Normalize so the three probabilities sum to exactly 1
        total_imp = imp_1 + imp_x + imp_2
        imp_1 = imp_1 / total_imp
        imp_x = imp_x / total_imp
        imp_2 = imp_2 / total_imp

        rows.append({
            "match_nr": i,
            "home": home,
            "away": away,
            "sv1": sv_1,
            "svx": sv_x,
            "sv2": sv_2,
            "oddset1": o1,
            "oddsetx": ox,
            "oddset2": o2,
            "imp1": imp_1,
            "impx": imp_x,
            "imp2": imp_2,
        })

    return pd.DataFrame(rows)