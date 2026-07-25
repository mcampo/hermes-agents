import json
import os
from pathlib import Path
import gspread
from google.oauth2.credentials import Credentials

MONTHS_ES = {
    "Enero": 2,
    "Febrero": 3,
    "Marzo": 4,
    "Abril": 5,
    "Mayo": 6,
    "Junio": 7,
    "Julio": 8,
    "Agosto": 9,
    "Septiembre": 10,
    "Octubre": 11,
    "Noviembre": 12,
    "Diciembre": 13
}

def load_task_config() -> dict:
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_expected_fixture() -> dict:
    fixture_path = Path(__file__).parent / "fixtures" / "expected.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_sheets_client(token_path: str) -> gspread.Client:
    expanded_token_path = os.path.expanduser(token_path)
    if not os.path.exists(expanded_token_path):
        raise FileNotFoundError(f"Authorized token file not found at {expanded_token_path}")
        
    with open(expanded_token_path, "r", encoding="utf-8") as f:
        info = json.load(f)
        
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    creds = Credentials.from_authorized_user_info(info, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc

def get_target_cell_coords(expected_fixture: dict) -> dict:
    target_tab = expected_fixture.get("target_tab", "")
    target_column_month = expected_fixture.get("target_column_month", "")
    
    col_index = MONTHS_ES.get(target_column_month)
    if not col_index:
        raise ValueError(f"Unknown month name: {target_column_month}")
        
    return {
        "tab": target_tab,
        "column_name": target_column_month,
        "col_index": col_index,
        "row": 15
    }
