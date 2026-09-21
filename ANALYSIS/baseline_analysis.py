"""
baseline_analysis.py
----------------
1. Parses a gameweek ("kupong") into 13 games with relevant features.
2. Computes descriptive features for any set of outcome combinations
   (odds bins, crowd % bins, rank features, aggregate odds/crowd products).
3. Derives historical filter thresholds via a data-driven hill-climbing
   search: starting from [min, max] per feature (100% historical retention),
   repeatedly tightens whichever feature's bound results in the highest
   remaining historical retention (ties broken by highest elimination),
   until no more tightening is possible without dropping combined
   historical retention below a target threshold (default 90%).
4. Filters a new gameweek's combinations using those thresholds.
"""

import pandas as pd
import numpy as np
import glob
import os
import time


# SETUP - paths relative to this file's location
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DIR = os.path.join(ROOT_DIR, "PROCESSED_DATA")
FILLED_DIR = os.path.join(PROCESSED_DIR, "filled_combinations")
RAW_DIR = os.path.join(ROOT_DIR, "RAW_DATA")

COMBO_FILES = {
    "Stryktipset": os.path.join(RAW_DIR, "all_combinations_stryktipset.csv"),
    "Europatipset": os.path.join(RAW_DIR, "all_combinations_europatipset.csv"),
    "Topptipset": os.path.join(RAW_DIR, "all_combinations_topptipset.csv"),
}

# Divide features into integer counts vs continuous aggregates
INTEGER_FEATURES = [
    "n_home", "n_draw", "n_away", "draws_tight", "draws_clearfav",
    "odds_1_1.5", "odds_1.5_2", "odds_2_2.5", "odds_2.5_3", "odds_3_4", "odds_4_6", "odds_6_plus",
    "svf_0_5", "svf_5_10", "svf_10_20", "svf_20_30", "svf_30_40", "svf_40_50",
    "svf_50_60", "svf_60_70", "svf_70_80", "svf_80_90", "svf_90_100",
    "rank_odds_1", "rank_odds_2", "rank_odds_3", "rank_svf_1", "rank_svf_2", "rank_svf_3",
]
AGGREGATE_FEATURES = ["total_odds", "total_svfolket", "sum_odds", "sum_svfolket"]


FEATURE_LABELS = {
    "n_home": "hemmasegrar (1:or)",
    "n_draw": "kryss (X)",
    "n_away": "bortasegrar (2:or)",
    "draws_tight": "kryss i matcher med en svag favorit (högsta sannolikhet max 40%)",
    "draws_clearfav": "kryss i matcher med en stark favorit (högsta sannolikhet minst 50%)",
    "odds_1_1.5": "val med odds 1.0-1.5",
    "odds_1.5_2": "val med odds 1.5-2.0",
    "odds_2_2.5": "val med odds 2.0-2.5",
    "odds_2.5_3": "val med odds 2.5-3.0",
    "odds_3_4": "val med odds 3.0-4.0",
    "odds_4_6": "val med odds 4.0-6.0",
    "odds_6_plus": "val med odds över 6.0",
    "svf_0_5": "val där Svenska Folket hade 0-5%",
    "svf_5_10": "val där Svenska Folket hade 5-10%",
    "svf_10_20": "val där Svenska Folket hade 10-20%",
    "svf_20_30": "val där Svenska Folket hade 20-30%",
    "svf_30_40": "val där Svenska Folket hade 30-40%",
    "svf_40_50": "val där Svenska Folket hade 40-50%",
    "svf_50_60": "val där Svenska Folket hade 50-60%",
    "svf_60_70": "val där Svenska Folket hade 60-70%",
    "svf_70_80": "val där Svenska Folket hade 70-80%",
    "svf_80_90": "val där Svenska Folket hade 80-90%",
    "svf_90_100": "val där Svenska Folket hade 90-100%",
    "rank_odds_1": "val som är odds-favoriten",
    "rank_odds_2": "val som är odds-tvåan",
    "rank_odds_3": "val som är odds-trean",
    "rank_svf_1": "val som är folkets favorit",
    "rank_svf_2": "val som är folkets tvåa",
    "rank_svf_3": "val som är folkets trea",
    "total_odds": "radens totala odds (produkt av alla 13 matchers odds)",
    "total_svfolket": "radens totala Svenska Folket-andel (produkt)",
    "sum_odds": "radens totala odds (summa)",
    "sum_svfolket": "radens totala Svenska Folket-andel (summa)",
}


def describe_applied_filters(thresholds, historical_features):
    """
    Builds human-readable descriptions of only the thresholds that were
    actually tightened from the historical min/max (i.e. filters that had
    a real effect), in the style "Tog bort alla rader med färre än X eller
    fler än Y <label>".

    Args:
        thresholds: dict {feature_name: (lower, upper)} from get_historical_intervals
        historical_features: DataFrame from build_historical_feature_matrix()

    Returns:
        list of str, one line per applied filter
    """
    lines = []
    for feature, (lo, hi) in thresholds.items():
        if feature not in historical_features.columns:
            continue
        global_min = historical_features[feature].min()
        global_max = historical_features[feature].max()
        if lo <= global_min and hi >= global_max:
            continue
        label = FEATURE_LABELS.get(feature, feature)
        if feature in AGGREGATE_FEATURES:
            lines.append(f"Tog bort alla rader där {label} låg utanför intervallet {lo:,.0f}-{hi:,.0f}")        
        else:
            lines.append(f"Tog bort alla rader med färre än {int(lo)} eller fler än {int(hi)} {label}")
    return lines




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


def kupong_csv_to_baseline(df):
    """
    Converts one historical kupong CSV (13 rows, one per match) into the same
    baseline format parse_kupong() produces, so historical rounds and new
    combos can be scored with the same feature-computation function.
    """
    df = df.copy()
    df = df.rename(columns={
        "matchnummer": "match_nr",
        "svenska_folket1": "sv1", "svenska_folketx": "svx", "svenska_folket2": "sv2",
    })
    inv = 1 / df[["oddset1", "oddsetx", "oddset2"]].astype(float)
    norm = inv.div(inv.sum(axis=1), axis=0)
    df["imp1"], df["impx"], df["imp2"] = norm["oddset1"], norm["oddsetx"], norm["oddset2"]
    return df[["match_nr", "sv1", "svx", "sv2", "oddset1", "oddsetx", "oddset2", "imp1", "impx", "imp2"]]


def _build_position_lookups(baseline_df):
    """
    For each match position (1-13), builds dicts mapping pick ('1','X','2')
    to odds and svf values, plus whether that position's draw (X) counts as
    'tight' (favorite weak) or 'clearfav' (favorite strong).
    """
    odds_lookup, svf_lookup = {}, {}
    draw_tight_flag, draw_clearfav_flag = {}, {}

    for _, row in baseline_df.iterrows():
        m = int(row["match_nr"])
        odds_lookup[m] = {"1": row["oddset1"], "X": row["oddsetx"], "2": row["oddset2"]}
        svf_lookup[m] = {"1": row["sv1"], "X": row["svx"], "2": row["sv2"]}
        max_prob = max(row["imp1"], row["impx"], row["imp2"])
        draw_tight_flag[m] = max_prob <= 0.40
        draw_clearfav_flag[m] = max_prob >= 0.50

    return odds_lookup, svf_lookup, draw_tight_flag, draw_clearfav_flag


def compute_features_vectorized(combos_df, baseline_df):
    """
    Computes descriptive features for every row (outcome combination) in
    combos_df, given the odds/crowd context in baseline_df. Vectorized
    across all combos per match position (13 iterations total) rather than
    one Python loop iteration per combo, to stay fast even at 1.6M+ rows.
    """
    odds_lookup, svf_lookup, draw_tight_flag, draw_clearfav_flag = _build_position_lookups(baseline_df)
    n = len(combos_df)

    n_home = np.zeros(n, dtype=int)
    n_draw = np.zeros(n, dtype=int)
    n_away = np.zeros(n, dtype=int)
    draws_tight = np.zeros(n, dtype=int)
    draws_clearfav = np.zeros(n, dtype=int)

    odds_bins_def = {
        "odds_1_1.5": (1.0, 1.5), "odds_1.5_2": (1.5, 2.0),
        "odds_2_2.5": (2.0, 2.5), "odds_2.5_3": (2.5, 3.0),
        "odds_3_4": (3.0, 4.0), "odds_4_6": (4.0, 6.0),
        "odds_6_plus": (6.0, float("inf")),
    }
    folket_bins_def = {
        "svf_0_5": (0, 5), "svf_5_10": (5, 10), "svf_10_20": (10, 20),
        "svf_20_30": (20, 30), "svf_30_40": (30, 40), "svf_40_50": (40, 50),
        "svf_50_60": (50, 60), "svf_60_70": (60, 70), "svf_70_80": (70, 80),
        "svf_80_90": (80, 90), "svf_90_100": (90, 100),
    }
    odds_bin_counts = {k: np.zeros(n, dtype=int) for k in odds_bins_def}
    folket_bin_counts = {k: np.zeros(n, dtype=int) for k in folket_bins_def}
    rank_odds_counts = {1: np.zeros(n, dtype=int), 2: np.zeros(n, dtype=int), 3: np.zeros(n, dtype=int)}
    rank_svf_counts = {1: np.zeros(n, dtype=int), 2: np.zeros(n, dtype=int), 3: np.zeros(n, dtype=int)}

    total_odds = np.ones(n, dtype=float)
    total_svf = np.ones(n, dtype=float)
    sum_odds = np.zeros(n, dtype=float)
    sum_svf = np.zeros(n, dtype=float)

    for i in range(1, 14):
        col = combos_df[f"m{i}"].astype(str).values
        odds_map = odds_lookup[i]
        svf_map = svf_lookup[i]

        pick_series = pd.Series(col)
        odds_val = pick_series.map(odds_map).astype(float).values
        svf_val = pick_series.map(svf_map).astype(float).values

        n_home += (col == "1")
        n_draw += (col == "X")
        n_away += (col == "2")

        is_draw = (col == "X")
        if draw_tight_flag[i]:
            draws_tight += is_draw
        if draw_clearfav_flag[i]:
            draws_clearfav += is_draw

        for k, (lo, hi) in odds_bins_def.items():
            odds_bin_counts[k] += ((odds_val >= lo) & (odds_val < hi)).astype(int)
        for k, (lo, hi) in folket_bins_def.items():
            folket_bin_counts[k] += ((svf_val >= lo) & (svf_val < hi)).astype(int)

        rank_order_odds = sorted(odds_map, key=odds_map.get)
        rank_order_svf = sorted(svf_map, key=svf_map.get, reverse=True)
        for pos_idx, symbol in enumerate(rank_order_odds, start=1):
            rank_odds_counts[pos_idx] += (col == symbol)
        for pos_idx, symbol in enumerate(rank_order_svf, start=1):
            rank_svf_counts[pos_idx] += (col == symbol)

        total_odds *= odds_val
        total_svf *= (svf_val / 100.0)
        sum_odds += odds_val
        sum_svf += svf_val

    features = {
        "n_home": n_home, "n_draw": n_draw, "n_away": n_away,
        "draws_tight": draws_tight, "draws_clearfav": draws_clearfav,
        "total_odds": total_odds, "total_svfolket": total_svf,
        "sum_odds": sum_odds, "sum_svfolket": sum_svf,
    }
    features.update(odds_bin_counts)
    features.update(folket_bin_counts)
    for pos_idx, v in rank_odds_counts.items():
        features[f"rank_odds_{pos_idx}"] = v
    for pos_idx, v in rank_svf_counts.items():
        features[f"rank_svf_{pos_idx}"] = v

    return pd.DataFrame(features)


def build_historical_feature_matrix(kupong_dir):
    """
    For every historical round CSV in kupong_dir, builds that round's own
    baseline (its own odds/crowd context) and computes features for its
    single winning outcome. Returns one row per historical round.
    """
    files = glob.glob(os.path.join(kupong_dir, "*.csv"))
    all_rows = []

    for path in files:
        df = pd.read_csv(path)
        baseline = kupong_csv_to_baseline(df)

        # The single winning outcome, as a 1-row "combo"
        winning_combo = {f"m{i}": [df.iloc[i - 1]["utfall"]] for i in range(1, 14)}
        combo_df = pd.DataFrame(winning_combo)

        feat = compute_features_vectorized(combo_df, baseline)
        all_rows.append(feat.iloc[0])

    return pd.DataFrame(all_rows).reset_index(drop=True)


def _init_thresholds(historical_features, features):
    """Start with [min, max] per feature - retains 100% of historical rows."""
    return {f: (historical_features[f].min(), historical_features[f].max()) for f in features}


def _compute_retention(historical_features, thresholds):
    """Fraction of historical rounds whose feature values ALL fall within thresholds."""
    mask = pd.Series(True, index=historical_features.index)
    for f, (lo, hi) in thresholds.items():
        mask &= (historical_features[f] >= lo) & (historical_features[f] <= hi)
    return mask.mean()


def _compute_eliminated(combo_features, thresholds):
    """Fraction of candidate combinations eliminated by the current thresholds."""
    mask = pd.Series(True, index=combo_features.index)
    for f, (lo, hi) in thresholds.items():
        mask &= (combo_features[f] >= lo) & (combo_features[f] <= hi)
    return 1 - mask.mean()


def _get_next_step(historical_features, feature, lo, hi, side, is_integer):
    """
    Returns the smallest meaningful tightening move for this feature's
    lower/upper bound:
    - integer features: +1 / -1
    - aggregate features: move to the next nearest historical data point
      strictly inside the current [lo, hi] range
    Returns None if no valid tightening move exists.
    """
    if is_integer:
        if side == "lower":
            new_val = lo + 1
            return new_val if new_val <= hi else None
        else:
            new_val = hi - 1
            return new_val if new_val >= lo else None
    else:
        values = historical_features[feature]
        if side == "lower":
            candidates = values[(values > lo) & (values <= hi)]
            return candidates.min() if not candidates.empty else None
        else:
            candidates = values[(values < hi) & (values >= lo)]
            return candidates.max() if not candidates.empty else None


def _optimize_all_features(historical_features, combo_features, target_retention):
    """
    Unified hill-climbing search over ALL features (integer + aggregate) in
    one loop. At each iteration, every feature proposes its smallest
    possible tightening move (both lower and upper side). Among candidate
    moves that keep combined historical retention >= target_retention, the
    move that results in the HIGHEST retention is preferred (i.e. the
    cheapest available improvement is always taken first); ties in
    resulting retention are broken by picking the move that eliminates the
    most combinations. Repeats until no valid move remains.
    """
    all_features = INTEGER_FEATURES + AGGREGATE_FEATURES
    thresholds = _init_thresholds(historical_features, all_features)

    iteration = 0
    while True:
        iteration += 1
        best_move = None
        best_retention = -1
        best_eliminated = -1

        for f in all_features:
            lo, hi = thresholds[f]
            is_integer = f in INTEGER_FEATURES

            for side in ("lower", "upper"):
                new_val = _get_next_step(historical_features, f, lo, hi, side, is_integer)
                if new_val is None:
                    continue

                trial = dict(thresholds)
                trial[f] = (new_val, hi) if side == "lower" else (lo, new_val)

                retention = _compute_retention(historical_features, trial)
                if retention < target_retention:
                    continue

                eliminated = _compute_eliminated(combo_features, trial)

                # Prefer the cheapest move (highest resulting retention) first;
                # break ties by picking the move that eliminates the most combos
                is_better = (
                    retention > best_retention
                    or (retention == best_retention and eliminated > best_eliminated)
                )
                if is_better:
                    best_retention = retention
                    best_eliminated = eliminated
                    best_move = (f, side, new_val)

        if best_move is None:
            print(f"[INFO] Converged after {iteration - 1} moves. No more valid tightening.")
            break

        f, side, new_val = best_move
        lo, hi = thresholds[f]
        thresholds[f] = (new_val, hi) if side == "lower" else (lo, new_val)

    return thresholds


def get_historical_intervals(kupong_dir, reference_baseline_df, combo_features, target_retention=0.90):
    """
    Runs the full data-driven interval search:
    1. Builds the historical feature matrix from every past round
    2. Runs the unified hill-climbing search (integer + aggregate features
       together) to find the tightest thresholds that keep at least
       target_retention of historical winning rows

    Args:
        kupong_dir: folder of historical kupong CSVs for this game type
        reference_baseline_df: this week's baseline (from parse_kupong) -
            only used to know which combo_features columns exist
        combo_features: pre-computed features for this week's full set of
            candidate combinations (from compute_features_vectorized)
        target_retention: minimum fraction of historical winning rows that
            must still satisfy the combined thresholds (default 0.90)

    Returns:
        dict of {feature_name: (lower, upper)}
    """
    print(f"[INFO] Building historical feature matrix from {kupong_dir}...")
    t0 = time.time()
    historical_features = build_historical_feature_matrix(kupong_dir)
    print(f"[INFO] Built matrix for {len(historical_features)} historical rounds in {time.time() - t0:.1f}s")

    print(f"[INFO] Running threshold search (target retention: {target_retention:.0%})...")
    t0 = time.time()
    thresholds = _optimize_all_features(historical_features, combo_features, target_retention)
    print(f"[INFO] Search done in {time.time() - t0:.1f}s")

    retention = _compute_retention(historical_features, thresholds)
    eliminated = _compute_eliminated(combo_features, thresholds)
    print(f"[RESULT] Final retention: {retention:.1%} | eliminated: {eliminated:.1%}")

    return thresholds, historical_features
    

def filter_combinations_by_intervals(game_type, baseline_df, thresholds, out_dir=FILLED_DIR):
    """
    Loads all_combinations_<game_type>.csv, computes features for every
    candidate combination, drops rows outside the given thresholds, and
    saves the reduced set to CSV.
    """
    t0 = time.time()
    combos = pd.read_csv(COMBO_FILES[game_type], dtype=str, low_memory=False)
    n_before = len(combos)
    print(f"[INFO] Loaded {n_before:,} combos for {game_type}")

    combo_features = compute_features_vectorized(combos, baseline_df)

    mask = pd.Series(True, index=combo_features.index)
    for feature, (low, high) in thresholds.items():
        if feature in combo_features.columns:
            mask &= (combo_features[feature] >= low) & (combo_features[feature] <= high)

    filtered = combos[mask].reset_index(drop=True)
    n_after = len(filtered)

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"filtered_combinations_{game_type.lower()}.csv")
    filtered.to_csv(out_path, index=False)
    print(f"[RESULT] {game_type}: {n_before:,} -> {n_after:,} after filtering ({out_path})")
    print(f"[INFO] filter_combinations_by_intervals runtime: {time.time() - t0:.2f} sec")

    return out_path