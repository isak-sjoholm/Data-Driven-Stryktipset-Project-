"""
generate_isak_picks.py
----------------------
Generates Isak's weekly picks with the same optimisation logic as the
Stryktipset Optimizer page and appends them to "Current Round" as one row
(timestamp, player_name, game_type, game_1 ... game_13), exactly like the
Lovable submit does.

Logic (288 rows = 2^5 * 3^2 = 5 half-hedges and 2 full-hedges):
  1. Every match starts as a spik on the sign with the lowest odds.
  2. Every other sign gets the value (p - streck/100) * p, where p is the
     odds-implied probability normalised to sum to 1 within the match.
  3. Signs are taken in order of value. A sign is added if there is room:
     1 -> 2 signs needs a free half-hedge, 2 -> 3 signs needs a free
     full-hedge (which frees the half-hedge the match was using).

Does nothing if Isak already has a row in "Current Round" or if the kupong
is a placeholder (no active round).

Usage:
    python -m AUTOMATION.generate_isak_picks
    python -m AUTOMATION.generate_isak_picks --dry-run
"""

import sys
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

SERVICE_ACCOUNT_FILE = "stryktipset-priors-automation-27f390beda4d.json"
SHEET_ID = "1O7dHCXAblAGXLAzOKYQ93hr7DTkFUv7iqEg2aUkaidY"
CURRENT_TAB = "Current Round"
KUPONG_HEADER = "kupong_raw_stryktipset"
PLAYER = "Isak"
HALV_ALLOWED = 5
HEL_ALLOWED = 2
SIGNS = "1X2"


def read_kupong(ws):
    """Returns [(odds, streck), ...] for the 13 matches, or None if the kupong is missing or a placeholder."""
    rows = ws.get_all_values()
    column = [h.strip().lower() for h in rows[0]].index(KUPONG_HEADER)
    text = next((r[column] for r in rows[1:] if len(r) > column and r[column].strip()), None)
    if not text:
        return None
    matches = []
    for game in text.split(";"):
        parts = [p.strip() for p in game.split(",")]
        if parts[1] == "NA":
            return None
        streck_1, streck_x, streck_2, odds_1, odds_x, odds_2 = map(float, parts[-6:])
        matches.append(({"1": odds_1, "X": odds_x, "2": odds_2},
                        {"1": streck_1, "X": streck_x, "2": streck_2}))
    return matches if len(matches) == 13 else None


def choose_signs(matches):
    """Returns the chosen signs per match, e.g. [['1'], ['1', 'X'], ...]."""
    chosen = [[min(SIGNS, key=lambda s: (odds[s], streck[s]))] for odds, streck in matches]

    ranked = []
    for i, (odds, streck) in enumerate(matches):
        total = sum(1 / odds[s] for s in SIGNS)
        for s in SIGNS:
            if s != chosen[i][0]:
                p = (1 / odds[s]) / total
                ranked.append(((p - streck[s] / 100) * p, i, s))
    ranked.sort(key=lambda r: -r[0])

    halv = hel = 0
    for _, i, s in ranked:
        if len(chosen[i]) == 1 and halv < HALV_ALLOWED:
            chosen[i].append(s)
            halv += 1
        elif len(chosen[i]) == 2 and hel < HEL_ALLOWED:
            chosen[i].append(s)
            halv -= 1
            hel += 1
    return chosen


def main():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    ws = gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(CURRENT_TAB)

    if PLAYER in [name.strip() for name in ws.col_values(2)]:
        print(f"[INFO] {PLAYER} already has a row in '{CURRENT_TAB}' - nothing to do.")
        return
    matches = read_kupong(ws)
    if matches is None:
        print("[WARN] No active kupong found (missing or placeholder) - nothing written.")
        return

    picks = [",".join(s for s in SIGNS if s in signs) for signs in choose_signs(matches)]
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    row = [timestamp, PLAYER, "Stryktipset"] + picks
    print(row)

    if "--dry-run" in sys.argv:
        print("[DRY RUN] Nothing written.")
        return
    ws.append_row(row, value_input_option="RAW", table_range="A1")
    print(f"[INFO] Wrote {PLAYER}'s picks to '{CURRENT_TAB}'")


if __name__ == "__main__":
    main()