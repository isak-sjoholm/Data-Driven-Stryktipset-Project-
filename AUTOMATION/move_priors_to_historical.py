"""
move_priors_to_historical.py
------------------------------
Moves last week's priors from "Current Round" to "Historical Rounds" in
Google Sheets. Must run before new experts start filling in priors for
the next round, to avoid confusion.

Typically runs Friday evening or Saturday morning (before new priors
start coming in).

Usage:
    python -m AUTOMATION.move_priors_to_historical
    python -m AUTOMATION.move_priors_to_historical --dry-run
"""

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import os
import time
import sys

SERVICE_ACCOUNT_FILE = "stryktipset-priors-automation-27f390beda4d.json"
SHEET_ID = "1O7dHCXAblAGXLAzOKYQ93hr7DTkFUv7iqEg2aUkaidY"
CURRENT_TAB = "Current Round"
HISTORICAL_TAB = "Historical Rounds"

# Lock file to prevent parallel runs
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK_FILE = os.path.join(ROOT_DIR, ".cache", "move_priors.lock")


def acquire_lock():
    """Tries to acquire the lock. Returns True if acquired, False otherwise."""
    lock_dir = os.path.dirname(LOCK_FILE)
    os.makedirs(lock_dir, exist_ok=True)

    if os.path.exists(LOCK_FILE):
        lock_age = time.time() - os.path.getmtime(LOCK_FILE)
        if lock_age > 600:  # 10 minutes - stale lock from a stuck process
            print(f"[WARN] Stale lock file found ({int(lock_age / 60)} min old). Removing it...")
            try:
                os.remove(LOCK_FILE)
            except Exception:
                pass
        else:
            print("[WARN] Lock file already exists (another process may be running).")
            print("[INFO] Waiting up to 30 seconds...")
            for _ in range(30):
                time.sleep(1)
                if not os.path.exists(LOCK_FILE):
                    break
            if os.path.exists(LOCK_FILE):
                print("[ERROR] Could not acquire lock - another process is still running.")
                return False

    try:
        with open(LOCK_FILE, "w") as f:
            f.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
        return True
    except Exception as e:
        print(f"[ERROR] Could not create lock file: {e}")
        return False


def release_lock():
    """Removes the lock file."""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


def move_priors_to_historical(dry_run=False):
    """
    Moves all priors from "Current Round" to "Historical Rounds".

    Args:
        dry_run: if True, only reports what would be moved without making
            any changes
    """
    print("=" * 80)
    print("MOVING PRIORS TO HISTORICAL ROUNDS")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()

    if not dry_run:
        if not acquire_lock():
            print("[ERROR] Could not acquire lock - exiting to avoid a duplicate move.")
            return False

    try:
        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(SHEET_ID)

        try:
            ws_current = sheet.worksheet(CURRENT_TAB)
        except Exception:
            print(f"[ERROR] Could not find tab '{CURRENT_TAB}'")
            return False

        try:
            ws_historical = sheet.worksheet(HISTORICAL_TAB)
        except Exception:
            print(f"[WARN] Tab '{HISTORICAL_TAB}' doesn't exist. Creating it...")
            ws_historical = sheet.add_worksheet(title=HISTORICAL_TAB, rows=1000, cols=20)
            headers = ws_current.row_values(1)
            ws_historical.append_row(headers)
            print(f"[INFO] Created tab '{HISTORICAL_TAB}'")

        print(f"[INFO] Reading data from '{CURRENT_TAB}'...")

        headers = ws_current.row_values(1)
        clean_headers = [h for h in headers if h and str(h).strip()]
        expected_headers = clean_headers if len(clean_headers) > 0 else headers

        try:
            df_current = pd.DataFrame(ws_current.get_all_records(expected_headers=expected_headers))
        except Exception:
            df_current = pd.DataFrame(ws_current.get_all_records())

        if df_current.empty:
            print("[INFO] No data in Current Round to move.")
            print("[INFO] Current Round is already empty - nothing to do.")
            return True

        print(f"[INFO] Found {len(df_current)} rows to move")
        print(f"[INFO] Experts: {df_current['player_name'].nunique()} unique")
        print()

        df_current["moved_to_historical"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        historical_headers_raw = ws_historical.row_values(1)
        historical_headers = [h for h in historical_headers_raw if h and str(h).strip()]

        if not historical_headers:
            headers = list(df_current.columns)
            ws_historical.append_row(headers)
            historical_headers = headers
            print(f"[INFO] Created headers in Historical Rounds: {len(historical_headers)} columns")

        print(f"[INFO] Historical Rounds has {len(historical_headers)} columns")
        print(f"[INFO] Current Round has {len(df_current.columns)} columns")

        # Match columns by header name, not position - ensures data lands in
        # the right columns even if the tab orderings differ
        df_current_filled = df_current.fillna("")
        rows_to_add = []
        for _, row in df_current_filled.iterrows():
            row_dict = row.to_dict()
            row_list = []
            for header in historical_headers:
                if header in row_dict:
                    val = row_dict[header]
                    if pd.isna(val) or val == "" or val is None:
                        row_list.append("")
                    else:
                        row_list.append(str(val))
                else:
                    row_list.append("")
            rows_to_add.append(row_list)

        print(f"[INFO] Matched {len(rows_to_add)} rows against Historical headers")

        if rows_to_add:
            first_row_non_empty = sum(1 for val in rows_to_add[0] if val and str(val).strip())
            print(f"[INFO] Verification: first row has {first_row_non_empty} non-empty values")
            if first_row_non_empty == 0:
                print("[WARN] First row is empty! Checking DataFrame...")
                print(f"[WARN] DataFrame columns with data: {[c for c in df_current.columns if not df_current[c].isna().all()][:10]}")

        all_values = ws_current.get_all_values()

        if dry_run:
            rows_to_delete = len(all_values) - 1 if len(all_values) > 1 else 0
            print(f"[DRY RUN] Would write {len(rows_to_add)} rows to '{HISTORICAL_TAB}'...")
            print(f"[DRY RUN] Would clear {rows_to_delete} rows from '{CURRENT_TAB}'...")
            print("\n[DRY RUN] No changes made. Run without --dry-run to actually move.")
            return True

        current_check = ws_current.get_all_values()
        if len(current_check) <= 1:
            print("[INFO] Current Round is already empty (may have been moved by another process).")
            print("[INFO] Nothing to do - exiting.")
            return True

        print(f"[INFO] Writing {len(rows_to_add)} rows to '{HISTORICAL_TAB}'...")

        if not rows_to_add or all(not any(str(val).strip() for val in row) for row in rows_to_add):
            print("[ERROR] No data to write (all rows are empty)!")
            print("[INFO] Exiting to avoid writing empty rows.")
            return False

        ws_historical.append_rows(rows_to_add, value_input_option="USER_ENTERED")
        print("[INFO] Data written to Historical Rounds")

        print(f"[INFO] Clearing '{CURRENT_TAB}'...")
        final_check = ws_current.get_all_values()
        if len(final_check) > 1:
            ws_current.delete_rows(2, len(final_check))
            print(f"[INFO] Cleared {len(final_check) - 1} rows from Current Round")
        else:
            print("[INFO] Current Round was already empty (may have been cleared by another process)")

        print()
        print("=" * 80)
        print("DONE!")
        print(f"Moved {len(df_current)} rows from '{CURRENT_TAB}' to '{HISTORICAL_TAB}'")
        print("Current Round is now empty and ready for new priors")
        print("=" * 80)

        return True

    except Exception as e:
        print(f"[ERROR] Failed to move priors: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if not dry_run:
            release_lock()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv or "-d" in sys.argv

    if dry_run:
        print("[INFO] DRY RUN MODE - no changes will be made\n")

    success = move_priors_to_historical(dry_run=dry_run)
    if success:
        print("\n[INFO] Process succeeded!")
    else:
        print("\n[ERROR] Process failed!")
        sys.exit(1)
        