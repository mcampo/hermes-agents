import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

def get_config_path() -> Path:
    return Path(__file__).parent.parent / "config.json"

def load_config() -> Dict[str, Any]:
    config_path = get_config_path()
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_api_key(provider: str) -> str:
    env_var = f"{provider.upper()}_API_KEY"
    return os.environ.get(env_var, "")

def load_sheets_config() -> Optional[Dict[str, Any]]:
    try:
        config = load_config()
        return config.get("google_sheets")
    except Exception:
        return None
