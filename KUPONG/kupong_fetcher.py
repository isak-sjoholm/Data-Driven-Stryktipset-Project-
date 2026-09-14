"""
kupong_fetcher.py
-----------------
Fetches the current round's kupong (coupon) string from Google Sheets.
"""

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials


SERVICE_ACCOUNT_FILE = "stryktipset-priors-automation-27f390beda4d.json"
SHEET_ID = "1O7dHCXAblAGXLAzOKYQ93hr7DTkFUv7iqEg2aUkaidY"
TAB_NAME = "Current Round"


def check_kupong_in_sheets(game_type="Stryktipset"):
    """
    Checks whether a kupong string already exists in Google Sheets for the
    given game type.

    Args:
        game_type: which game type's kupong column to look for
            (e.g. "Stryktipset" -> column "kupong_raw_stryktipset")

    Returns:
        (bool, str): (True, kupong_string) if found, (False, None) otherwise
    """
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SHEET_ID).worksheet(TAB_NAME)

    headers = ws.row_values(1)
    clean_headers = [h for h in headers if h and str(h).strip()]
    expected_headers = clean_headers if clean_headers else headers

    try:
        df = pd.DataFrame(ws.get_all_records(expected_headers=expected_headers))
    except Exception:
        df = pd.DataFrame(ws.get_all_records())

    col_name = f"kupong_raw_{game_type.lower()}"
    if col_name in df.columns:
        for val in df[col_name]:
            if pd.notna(val) and str(val).strip():
                kupong_val = str(val).strip()
                if len(kupong_val) > 10:
                    print(f"[INFO] Found {game_type} kupong in column: {col_name}")
                    return True, kupong_val

    print(f"[INFO] No kupong found for {game_type}.")
    return False, None



def write_kupong_to_sheets(kupong_raw, game_type="Stryktipset"):
    """
    Writes a kupong string to Google Sheets, in a game-type-specific column
    (e.g. "kupong_raw_stryktipset"). Creates the column if it doesn't exist.

    Args:
        kupong_raw: kupong string, same format as parse_kupong() expects
        game_type: which game type's column to write to
    """
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SHEET_ID).worksheet(TAB_NAME)

    headers = ws.row_values(1)
    kupong_col_name = f"kupong_raw_{game_type.lower()}"
    clean_headers = [h for h in headers if h and str(h).strip()]

    if kupong_col_name not in clean_headers:
        col_to_insert = None
        for i, header in enumerate(headers):
            if not header or not str(header).strip():
                col_to_insert = i + 1
                ws.update_cell(1, col_to_insert, kupong_col_name)
                break

        if col_to_insert is None:
            all_values = ws.get_all_values()
            num_rows = len(all_values) if all_values else 1
            new_col = [[kupong_col_name]] + [[""] for _ in range(1, num_rows)]
            ws.insert_cols(new_col, len(headers) + 1)
            col_to_insert = len(headers) + 1

        headers = ws.row_values(1)
        print(f"[INFO] Added/updated column '{kupong_col_name}' in Google Sheets")

    kupong_col_idx = headers.index(kupong_col_name) + 1
    ws.update_cell(2, kupong_col_idx, kupong_raw)

    print(f"[INFO] Wrote kupong to Google Sheets ({len(kupong_raw)} chars, game_type={game_type})")