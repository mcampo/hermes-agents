import sys
import os
import json
from typing import Dict, Any
from results import FIELDNAMES

def append_result_to_sheet(row: Dict[str, Any], spreadsheet_id: str, sheet_name: str, token_path: str):
    """
    Appends a row of evaluation results to a Google Spreadsheet.
    Authenticates using a pre-authorized token JSON file.
    If the sheet is completely empty, it writes the header row first.
    All exceptions are caught and logged as a warning to stdout.
    """
    try:
        import gspread
        from google.oauth2.credentials import Credentials
        
        # Expand user path (e.g., ~/.hermes/authorized_user.json)
        expanded_token_path = os.path.expanduser(token_path)
        
        if not os.path.exists(expanded_token_path):
            raise FileNotFoundError(f"Authorized token file not found at {expanded_token_path}")
            
        with open(expanded_token_path, "r", encoding="utf-8") as f:
            info = json.load(f)
            
        # Define scopes
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # Authorize using the credentials loaded from the token file
        creds = Credentials.from_authorized_user_info(info, scopes=scopes)
        gc = gspread.authorize(creds)
        
        # Open the spreadsheet by ID
        sh = gc.open_by_key(spreadsheet_id)
        
        # Open the worksheet by name
        worksheet = sh.worksheet(sheet_name)
        
        # Check if the worksheet is completely empty
        values = worksheet.get_all_values()
        if not values or (len(values) == 1 and not any(values[0])):
            worksheet.append_row(FIELDNAMES)
            
        # Align row values with FIELDNAMES
        row_list = []
        for field in FIELDNAMES:
            val = row.get(field, "")
            if isinstance(val, (list, dict)):
                val = json.dumps(val)
            row_list.append(val)
            
        worksheet.append_row(row_list, value_input_option="USER_ENTERED")
        print(f"  Successfully appended results to Google Sheet '{sheet_name}'.")
        
    except Exception as e:
        print(f"  WARNING: Failed to write to Google Sheets: {e}")

def generate_google_token(client_secret_path: str, token_output_path: str):
    """
    Runs the OAuth2 authorization flow locally (opening a browser)
    and saves the pre-authorized token JSON file.
    """
    import gspread
    
    expanded_secret = os.path.expanduser(client_secret_path)
    expanded_token = os.path.expanduser(token_output_path)
    
    print(f"Starting Google OAuth2 authorization flow...")
    print(f"Reading client secrets from: {expanded_secret}")
    print(f"Token will be saved to: {expanded_token}")
    
    # If the token output file already exists, remove it so we force a new auth flow
    if os.path.exists(expanded_token):
        os.remove(expanded_token)
        
    gspread.oauth(
        credentials_filename=expanded_secret,
        authorized_user_filename=expanded_token
    )
    print("Authorization successful! Token file created.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Google Sheets Token Generator")
    parser.add_argument("client_secret_path", help="Path to google_client_secret.json")
    parser.add_argument("token_output_path", help="Path where authorized_user.json will be saved")
    args = parser.parse_args()
    
    generate_google_token(args.client_secret_path, args.token_output_path)
