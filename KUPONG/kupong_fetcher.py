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
    