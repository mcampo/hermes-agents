import json
import sys
from pathlib import Path

# Add parent directory to path so we can import sheets_helper
sys.path.insert(0, str(Path(__file__).parent))
import sheets_helper

def dump():
    print("Starting state dump for ipc-indec-angelica...")
    config = sheets_helper.load_task_config()
    expected = sheets_helper.load_expected_fixture()
    
    token_path = config.get("sheets", {}).get("token_path", "")
    spreadsheet_id = config.get("sheets", {}).get("spreadsheet_id", "")
    
    gc = sheets_helper.get_sheets_client(token_path)
    sh = gc.open_by_key(spreadsheet_id)
    
    coords = sheets_helper.get_target_cell_coords(expected)
    tab_name = coords.get("tab")
    
    worksheet = sh.worksheet(tab_name)
    
    # Get all formulas/values
    print(f"Fetching all values (formulas) from tab {tab_name}...")
    data = worksheet.get_all_values(value_render_option="FORMULA")
    
    fixture_path = Path(__file__).parent / "fixtures" / "original_sheet.json"
    print(f"Saving to {fixture_path}...")
    
    with open(fixture_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    print("Done! State dumped successfully.")

if __name__ == "__main__":
    dump()
