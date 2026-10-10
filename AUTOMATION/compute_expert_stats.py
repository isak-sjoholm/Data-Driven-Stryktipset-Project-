"""
compute_expert_stats.py
-----------------------
Reads expert picks from "Historical Rounds" and actual outcomes plus payouts
from "Historical Results", scores every expert for every finished round, and
writes two tabs that the Lovable page can read:

  Stats         one row per expert (average/max correct, spike hit rate, ROI)
  Stats Rounds  one row per expert and round (correct, rows, payout, ROI)

An expert's picks expand to every combination of their signs, and each
combination costs 1 kr. The payout is the number of those combinations with
13/12/11/10 correct times the round's payout per row (utd_13 ... utd_10).
A round is only scored once all 13 outcomes and all four payouts are filled
in on "Historical Results". If an expert has several rows for one round, the
latest one counts.

Usage:
    python -m AUTOMATION.compute_expert_stats
    python -m AUTOMATION.compute_expert_stats --dry-run
"""

import json
import re
import sys

import gspread
import numpy as np
import pandas as pd
from google.oauth2.service_account import Credentials

SERVICE_ACCOUNT_FILE = "stryktipset-priors-automation-27f390beda4d.json"
SHEET_ID = "1O7dHCXAblAGXLAzOKYQ93hr7DTkFUv7iqEg2aUkaidY"
EXPERTS = ["Ludde", "Isak", "Fredrik"]
GAMES = [f"game_{i}" for i in range(1, 14)]
PAYOUTS = {13: "utd_13", 12: "utd_12", 11: "utd_11", 10: "utd_10"}


def read_tab(sheet, name):
    """Returns a worksheet as a DataFrame, using row 1 as column names."""
    values = sheet.worksheet(name).get_all_values()
    return pd.DataFrame(values[1:], columns=values[0])


def symbols(value):
    """Extracts the signs 1, X, 2 from a pick like '1,X', '21' or '2.0'."""
    return sorted(set(re.sub("[^12X]", "", str(value).upper())))


def score_row(row):
    """
    Scores one expert row against the round's outcome.

    The polynomial holds, per number of correct matches, how many of the
    expert's combinations get exactly that many correct: a match with m signs
    contributes (m-1) + x if the outcome is among them, otherwise m.
    """
    poly = np.array([1])
    combos = 1
    hits = spikes = spike_hits = 0
    for game in GAMES:
        picks = symbols(row[game])
        if not picks:
            continue
        hit = row["res_" + game] in picks
        hits += hit
        combos *= len(picks)
        if len(picks) == 1:
            spikes += 1
            spike_hits += hit
        poly = np.convolve(poly, [len(picks) - 1, 1] if hit else [len(picks)])
    payout = sum(poly[k] * row[col] for k, col in PAYOUTS.items() if k < len(poly))
    return pd.Series({"hits": hits, "combos": combos, "spikes": spikes,
                      "spike_hits": spike_hits, "payout": payout})


def compute_stats(picks, results):
    """Returns (summary per expert, details per expert and round)."""
    picks = picks[picks["player_name"].isin(EXPERTS)].copy()
    picks["Omgång"] = pd.to_datetime(picks["Omgång"], errors="coerce").dt.strftime("%Y-%m-%d")
    picks["ts"] = pd.to_datetime(picks["timestamp"], utc=True, format="ISO8601", errors="coerce")
    picks = picks.sort_values("ts").drop_duplicates(["Omgång", "player_name"], keep="last")

    results = results.copy()
    results["Omgång"] = pd.to_datetime(results["Omgång"], errors="coerce").dt.strftime("%Y-%m-%d")
    results[GAMES] = results[GAMES].apply(lambda col: col.str.strip().str.upper())
    for col in PAYOUTS.values():
        results[col] = pd.to_numeric(results[col].str.replace(r"\s", "", regex=True), errors="coerce")
    results = results[results[GAMES].isin(["1", "X", "2"]).all(axis=1)
                      & results[list(PAYOUTS.values())].notna().all(axis=1)]
    results = results.rename(columns={g: "res_" + g for g in GAMES})

    df = picks.merge(results, on="Omgång")
    df = df.join(df.apply(score_row, axis=1))
    df["roi"] = df["payout"] - df["combos"]
    df = df.sort_values(["Omgång", "player_name"])

    details = df[["Omgång", "player_name", "hits", "combos", "payout", "roi"]].rename(
        columns={"player_name": "Expert", "hits": "Rätt", "combos": "Rader", "payout": "Utdelning", "roi": "ROI"})

    grouped = df.groupby("player_name")
    summary = pd.DataFrame({
        "Omgångar": grouped.size(),
        "Snitt rätt": grouped["hits"].mean().round(2),
        "Max rätt": grouped["hits"].max(),
        "Spik-träff %": (grouped["spike_hits"].sum() / grouped["spikes"].sum() * 100).round(1),
        "Snitt ROI (kr)": grouped["roi"].mean().round(0),
        "Total ROI (kr)": grouped["roi"].sum().round(0),
    }).reset_index().rename(columns={"player_name": "Expert"})
    return summary, details


def write_tab(sheet, name, df):
    """Replaces the contents of a tab (created if missing) with a DataFrame."""
    try:
        ws = sheet.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=name, rows=1000, cols=20)
    ws.clear()
    ws.update([df.columns.tolist()] + json.loads(df.to_json(orient="values")), value_input_option="RAW")


def main():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sheet = gspread.authorize(creds).open_by_key(SHEET_ID)

    summary, details = compute_stats(read_tab(sheet, "Historical Rounds"), read_tab(sheet, "Historical Results"))
    print(summary.to_string(index=False))

    if "--dry-run" in sys.argv:
        print("[DRY RUN] Nothing written.")
        return
    write_tab(sheet, "Stats", summary)
    write_tab(sheet, "Stats Rounds", details)
    print(f"[INFO] Wrote {len(summary)} rows to Stats and {len(details)} rows to Stats Rounds")


if __name__ == "__main__":
    main()