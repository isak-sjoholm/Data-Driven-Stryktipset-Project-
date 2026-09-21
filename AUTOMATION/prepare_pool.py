"""
prepare_pool.py
-----------------
Runs the heavy historical threshold search and filters the full set of
possible combinations down to a pool, independent of expert input (the
filtering only depends on odds/crowd data, not on the Bayesian-updated
probabilities, so it can run before experts submit their picks). Saves
the result to disk for saturday_automation.py to read later.

Intended to run once, a few hours before the Saturday deadline.

Usage:
    python -m AUTOMATION.prepare_pool
"""

import os
import json
import pandas as pd
from datetime import datetime

from KUPONG.kupong_fetcher import check_kupong_in_sheets
from ANALYSIS.baseline_analysis import (
    parse_kupong,
    compute_features_vectorized,
    get_historical_intervals,
    filter_combinations_by_intervals,
    describe_applied_filters,
    PROCESSED_DIR,
    RAW_DIR,
)


def prepare_pool(game_type="Stryktipset"):
    print("=" * 80)
    print(f"PREPARE POOL - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    print("\n[STEP 1] Fetching kupong...")
    has_kupong, raw_kupong = check_kupong_in_sheets(game_type)
    if not has_kupong:
        raise ValueError(f"No kupong found for {game_type}")
    baseline_df = parse_kupong(raw_kupong)
    print(f"[INFO] Kupong parsed ({len(baseline_df)} matches)")

    print("\n[STEP 2] Running historical threshold search and filtering...")
    combos = pd.read_csv(os.path.join(RAW_DIR, f"all_combinations_{game_type.lower()}.csv"), dtype=str, low_memory=False)
    total_before = len(combos)
    combo_features = compute_features_vectorized(combos, baseline_df)
    thresholds, historical_features = get_historical_intervals(
        os.path.join(PROCESSED_DIR, f"kuponger_{game_type.lower()}"),
        baseline_df,
        combo_features,
        target_retention=0.90,
    )
    filter_descriptions = describe_applied_filters(thresholds, historical_features)
    filtered_path = filter_combinations_by_intervals(game_type, baseline_df, thresholds)
    pool = pd.read_csv(filtered_path, dtype=str, low_memory=False)
    total_after = len(pool)
    print(f"[INFO] Pool after historical filtering: {total_after:,} rows")

    print("\n[STEP 3] Saving pool metadata...")
    pool_dir = os.path.join(PROCESSED_DIR, "filled_combinations")
    os.makedirs(pool_dir, exist_ok=True)
    meta_path = os.path.join(pool_dir, f"pool_meta_{game_type.lower()}.json")
    with open(meta_path, "w") as f:
        json.dump({
            "total_before": total_before,
            "total_after": total_after,
            "filter_descriptions": filter_descriptions,
            "generated_at": datetime.now().isoformat(),
        }, f, indent=2)
    print(f"[INFO] Saved metadata to {meta_path}")

    print("\n" + "=" * 80)
    print(f"DONE: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)


if __name__ == "__main__":
    prepare_pool("Stryktipset")