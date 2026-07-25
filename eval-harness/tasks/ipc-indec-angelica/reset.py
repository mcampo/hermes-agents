import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import gspread
import sheets_helper

def reset() -> None:
    print("Starting reset for ipc-indec-angelica...")
    config = sheets_helper.load_task_config()
    expected = sheets_helper.load_expected_fixture()
    
    token_path = config.get("sheets", {}).get("token_path", "")
    spreadsheet_id = config.get("sheets", {}).get("spreadsheet_id", "")
    
    try:
        gc = sheets_helper.get_sheets_client(token_path)
    except Exception as e:
        print(f"Error authenticating to Google Sheets: {e}")
        return
        
    try:
        coords = sheets_helper.get_target_cell_coords(expected)
    except Exception as e:
        print(f"Error determining target cell coordinates: {e}")
        return
        
    try:
        sh = gc.open_by_key(spreadsheet_id)
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"Spreadsheet not found: {spreadsheet_id}")
        return
        
    tab_name = coords.get("tab")
    try:
        worksheet = sh.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        print(f"Worksheet not found: {tab_name}")
        return
        
    # Restore original state
    original_sheet_path = Path(__file__).parent / "fixtures" / "original_sheet.json"
    try:
        with open(original_sheet_path, "r", encoding="utf-8") as f:
            original_data = json.load(f)
            
        print("Restoring full sheet state...")
        worksheet.clear()
        worksheet.update(values=original_data, range_name="A1", value_input_option="USER_ENTERED")
        print("Reset successful. Restored original sheet state.")
    except Exception as e:
        print(f"Error restoring original sheet state: {e}")

if __name__ == "__main__":
    reset()
