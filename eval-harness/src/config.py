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

def load_api_key(provider: str, profile: str = "eval") -> str:
    env_var = f"{provider.upper()}_API_KEY"
    val = os.environ.get(env_var)
    if val:
        return val
        
    env_file = Path.home() / ".hermes" / "profiles" / profile / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{env_var}="):
                    return line.split("=", 1)[1].strip(" '\"")
                    
    return ""

def load_sheets_config() -> Optional[Dict[str, Any]]:
    try:
        config = load_config()
        return config.get("google_sheets")
    except Exception:
        return None
