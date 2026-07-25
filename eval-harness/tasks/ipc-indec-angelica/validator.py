import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import re
import gspread
from gspread.utils import rowcol_to_a1
import sheets_helper

def validate(agent_output: str) -> dict:
    score = 0.0
    details = []
    
    try:
        config = sheets_helper.load_task_config()
        expected = sheets_helper.load_expected_fixture()
    except Exception as e:
        return {"score": 0.0, "details": [f"Config/Fixture load error: {e}"]}
        
    token_path = config.get("sheets", {}).get("token_path", "")
    spreadsheet_id = config.get("sheets", {}).get("spreadsheet_id", "")
    
    try:
        gc = sheets_helper.get_sheets_client(token_path)
    except Exception as e:
        return {"score": 0.0, "details": [f"Sheets access error: {e}"]}
        
    try:
        coords = sheets_helper.get_target_cell_coords(expected)
    except Exception as e:
        return {"score": 0.0, "details": [f"Coordinate error: {e}"]}
        
    try:
        sh = gc.open_by_key(spreadsheet_id)
        worksheet = sh.worksheet(coords.get("tab"))
    except Exception as e:
        return {"score": 0.0, "details": [f"Spreadsheet/Worksheet error: {e}"]}
        
    row = coords.get("row")
    col = coords.get("col_index")
    a1_label = rowcol_to_a1(row, col)
    
    try:
        # Check for non-target cell modifications
        original_sheet_path = Path(__file__).parent / "fixtures" / "original_sheet.json"
        with open(original_sheet_path, "r", encoding="utf-8") as f:
            original_data = json.load(f)
            
        current_data = worksheet.get_all_values(value_render_option="FORMULA")
        
        # We only care about ensuring that current_data doesn't deviate from original_data,
        # EXCEPT for the target cell.
        max_rows = max(len(original_data), len(current_data))
        for r in range(max_rows):
            orig_row = original_data[r] if r < len(original_data) else []
            curr_row = current_data[r] if r < len(current_data) else []
            
            max_cols = max(len(orig_row), len(curr_row))
            for c in range(max_cols):
                # Skip the target cell (row and col are 1-indexed)
                if r == (row - 1) and c == (col - 1):
                    continue
                    
                orig_val = str(orig_row[c]).strip() if c < len(orig_row) else ""
                curr_val = str(curr_row[c]).strip() if c < len(curr_row) else ""
                
                # Treat empty string and "None" equivalently for trailing empty cells
                if not orig_val and not curr_val:
                    continue
                    
                if orig_val != curr_val:
                    # STRICT PENALTY: Data destruction
                    details.append(f"FAIL: Data Destruction! Cell R{r+1}C{c+1} was modified from '{orig_val}' to '{curr_val}'")
                    return {"score": 0.0, "details": details}
                    
        # Proceed with target cell checks
        # Default value_render_option is FORMATTED_VALUE in acell
        formatted_cell = worksheet.acell(a1_label)
        cell_value = formatted_cell.value if formatted_cell.value else ""
        
        formula_cell = worksheet.acell(a1_label, value_render_option='FORMULA')
        cell_formula = formula_cell.value if formula_cell.value else ""
    except Exception as e:
        return {"score": 0.0, "details": [f"Cell read error: {e}"]}
        
    # Check 1: Cell is not empty
    if cell_value:
        score += 0.20
        details.append("PASS: Cell is populated")
    else:
        details.append(f"FAIL: Cell is empty. Read: '{cell_value}'")
        
    # Check 2: Raw formula starts with =HYPERLINK( and contains ;
    if str(cell_formula).upper().startswith("=HYPERLINK(") and ";" in str(cell_formula):
        score += 0.20
        details.append("PASS: Valid HYPERLINK formula with semicolon")
    else:
        details.append(f"FAIL: Invalid formula. Read: '{cell_formula}'")
        
    # Check 3: Displayed value matches regex
    if re.match(r"^\d+(,\d+)?%$", str(cell_value)):
        score += 0.20
        details.append("PASS: Percentage format valid")
    else:
        details.append(f"FAIL: Invalid percentage format. Read: '{cell_value}'")
        
    # Check 4: URL contains expected domain
    expected_domain = expected.get("expected_url_contains", "indec.gob.ar")
    if expected_domain in str(cell_formula):
        score += 0.20
        details.append(f"PASS: Formula contains expected domain '{expected_domain}'")
    else:
        details.append(f"FAIL: Formula missing expected domain '{expected_domain}'")
        
    # Check 5: Displayed value == expected value
    expected_value = expected.get("expected_value", "")
    if str(cell_value) == expected_value:
        score += 0.20
        details.append(f"PASS: Value matches expected '{expected_value}'")
    else:
        details.append(f"FAIL: Value '{cell_value}' != expected '{expected_value}'")
        
    # Handle floating point inaccuracies
    score = round(score, 2)
    return {"score": score, "details": details}
