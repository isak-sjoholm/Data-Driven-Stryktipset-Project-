"""
preprocessing.py
----------------
1. Loads raw CSV files of full historical data for Stryktipset/Europatipset/Topptipset.
2. Handles missing values, filters out irrelevant data & splits data into separate gameweeks.
3. Converts the gameweeks to a format suitable for an ML pipeline.
"""

import pandas as pd
import os


# SETUP - paths relative to this file's location, so it works regardless of
# where the repo is cloned (e.g. locally or in a GitHub Actions runner)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT_DIR, "RAW_DATA")
OUT_DIR = os.path.join(ROOT_DIR, "PROCESSED_DATA")


# Specify columns to use
relevant_cols = ["produktnamn", "omg", "matchnummer", "hemmalag", "bortalag", # metadata
    "oddset1", "oddsetx", "oddset2", # odds data
    "svenska_folket1", "svenska_folketx", "svenska_folket2", #crowd data
    "utfall", "correct_row", "utd13", "utd12", "utd11", "utd10" # outcome/prize pot datas
]


# Function to save relevant info from raw data files
def load_and_filter_raw_files(RAW_DIR, stats_file, summary_file, OUT_DIR, relevant_cols):
    """
    1. Reads the stats and summary CSVs
    2. Filters down to relevant columns
    3. Drops rows with missing/bad values
    4. Saves the filtered version to a new CSV
    """

    # Define path
    stats_path = os.path.join(RAW_DIR, stats_file)
    summary_path = os.path.join(RAW_DIR, summary_file)

    # Read CSVs
    df_stats = pd.read_csv(stats_path, sep=";", encoding="utf-8")
    df_summary = pd.read_csv(summary_path, sep=";", encoding="utf-8")

    # Drop rows with bad/empty data
    summary_keep = ["omg", "produktnamn", "correct_row", "utd13", "utd12", "utd11", "utd10"]
    df_summary = df_summary[summary_keep].dropna(subset=["omg"])
    df_stats = df_stats.dropna(subset=["omg", "produktnamn"])

    # Build a composite key (round + product name) on both dfs
    df_stats = df_stats.assign(key=df_stats["omg"].astype(str) + "_" + df_stats["produktnamn"])
    df_summary = df_summary.assign(key=df_summary["omg"].astype(str) + "_" + df_summary["produktnamn"])
    df_summary = df_summary.drop_duplicates(subset="key")

    # Merge stats (per-match data) with summary (per-round prize-pot data) on the composite key
    merge_cols = ["key", "correct_row", "utd13", "utd12", "utd11", "utd10"]
    df = pd.merge(df_stats, df_summary[merge_cols], on="key", how="inner", validate="many_to_one")

    # Keep only the columns we actually care about + key
    cols_to_keep = ["key"] + relevant_cols
    df = df[cols_to_keep]

    # Drop any row that has a missing value in any of the kept columns
    df_filtered = df.dropna()

    # Sanity-check odds: keep only rows where all three odds are within a plausible range (1.00-50.00)
    odds_cols = ["oddset1", "oddsetx", "oddset2"]
    mask_odds = df_filtered[odds_cols].apply(lambda col: col.between(1.00, 50.00))
    df_filtered = df_filtered[mask_odds.all(axis=1)]

    # Sanity-check crowd percentages: keep only rows where all three Svenska Folket percentages are within a plausible range (1-100)
    folk_cols = ["svenska_folket1", "svenska_folketx", "svenska_folket2"]
    mask_folk = df_filtered[folk_cols].apply(lambda col: col.between(1, 100))
    df_filtered = df_filtered[mask_folk.all(axis=1)]

    # Keep only rows where the actual outcome is a valid value (1, X, or 2)
    df_filtered = df_filtered[df_filtered["utfall"].isin(["1", "X", "2"])]

    # Keep only rounds where the prize pot columns aren't all zero
    utd_cols = ["utd13", "utd12", "utd11", "utd10"]
    df_filtered = df_filtered[df_filtered[utd_cols].sum(axis=1) > 0]

    # Build the output filename & save the cleaned DataFrame to OUT_DIR
    out_filename = stats_file.replace(".csv", "_filtered.csv").lower().replace(" ", "_")
    out_path = os.path.join(OUT_DIR, out_filename)
    df_filtered.to_csv(out_path, index=False)

    # Report how many rows survived the filtering
    print(f"Saved filtered file: {out_filename} ({len(df_filtered)} rows)")
    return df_filtered


# Function to split the combined filtered CSV of all past data into one CSV per round
def save_kuponger_from_csv(filenames, OUT_DIR):
    """
    Takes filtered CSV files and splits them into one CSV per round,
    per game type. Rounds with an incomplete number of matches are dropped.
    """

    # Expected number of matches per game type - used to detect complete rounds
    game_types = {"Stryktipset": 13, "Europatipset": 13, "Topptipset": 8}

    saved_counts = {gt: 0 for gt in game_types}

    # For each filtered CSV file:
    for file in filenames:

        # Find the CSV path
        in_path = os.path.join(OUT_DIR, file)

        # Load it as a df
        df = pd.read_csv(in_path)

        for game_type, expected_games in game_types.items():

            # Filter rows that contain the game_type in produktnamn
            df_game = df[df["produktnamn"].str.contains(game_type, case=False, na=False)].copy()

            # Group by key
            grouped = df_game.groupby("key")

            save_dir = os.path.join(OUT_DIR, f"kuponger_{game_type.lower()}")
            os.makedirs(save_dir, exist_ok=True)

            for omg, group in grouped:

                # Only save rounds that have exactly the expected number of matches
                if len(group) == expected_games:
                    filename = f"{game_type.lower()}_{omg}.csv".replace(" ", "_")
                    out_path = os.path.join(save_dir, filename)
                    group.to_csv(out_path, index=False)
                    saved_counts[game_type] += 1

    for gt, count in saved_counts.items():
        print(f"{count} complete kuponger saved for {gt}.")


# Converts all individual kupong CSVs in a folder to a single flat ML-ready CSV with one row per game, and one column per feature
def convert_kuponger_to_ml_rows(kupong_dirs, out_dir):
    """
    Reads every kupong CSV for a game type and flattens them into one row per
    individual game (not per round), keeping only the features needed for
    downstream modeling (odds, crowd %, and one-hot encoded outcome).
    """

    for game_type, kupong_dir in kupong_dirs.items():

        all_rows = []

        for filename in sorted(os.listdir(kupong_dir)):
            if not filename.endswith(".csv"):
                continue

            path = os.path.join(kupong_dir, filename)
            df = pd.read_csv(path)

            for row in df.itertuples():
                utfall = row.utfall
                all_rows.append({
                    "game_type": game_type, "key": row.key, "matchnummer": row.matchnummer, # Metadata
                    "oddset1": row.oddset1, "oddsetx": row.oddsetx, "oddset2": row.oddset2, # Odds data
                    "svfolket1": row.svenska_folket1, "svfolketx": row.svenska_folketx, "svfolket2": row.svenska_folket2, # Crowd data
                    "utfall": utfall, "utfall_1": 1 if utfall == "1" else 0, "utfall_X": 1 if utfall == "X" else 0, "utfall_2": 1 if utfall == "2" else 0} # Outcome data
                )

        df_out = pd.DataFrame(all_rows)
        out_csv_path = os.path.join(out_dir, f"ML_{game_type.lower()}.csv")
        df_out.to_csv(out_csv_path, index=False)
        print(f"Saved ML dataset for {game_type} of {len(df_out)} rows.")


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)

    # Save relevant info from raw data files
    df_stryk = load_and_filter_raw_files(RAW_DIR, stats_file="TipsXtra_Stryk_Euro_Statistik_Detaljer-5.csv", summary_file="TipsXtra_Stryk_Euro_Statistik_Summering-5.csv", OUT_DIR=OUT_DIR, relevant_cols=relevant_cols)
    df_topp = load_and_filter_raw_files(RAW_DIR, stats_file="TipsXtra_Topptipset_Statistik_Detaljer-3.csv", summary_file="TipsXtra_Topptipset_Statistik_Summering-2.csv", OUT_DIR=OUT_DIR, relevant_cols=relevant_cols)

    # Split the combined filtered CSVs into one CSV per round
    save_kuponger_from_csv(filenames=["tipsxtra_stryk_euro_statistik_detaljer-5_filtered.csv", "tipsxtra_topptipset_statistik_detaljer-3_filtered.csv"], OUT_DIR=OUT_DIR)

    # Converts all individual kupong CSVs in a folder to a single flat ML-ready CSV
    kupong_dirs = {"Stryktipset": os.path.join(OUT_DIR, "kuponger_stryktipset"), "Europatipset": os.path.join(OUT_DIR, "kuponger_europatipset"), "Topptipset": os.path.join(OUT_DIR, "kuponger_topptipset")}
    convert_kuponger_to_ml_rows(kupong_dirs, OUT_DIR)