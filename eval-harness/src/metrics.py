import sqlite3
import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

def get_session_metrics(profile: str, session_id: str) -> Optional[Dict[str, Any]]:
    db_path = Path.home() / ".hermes" / "profiles" / profile / "state.db"
    if not db_path.exists():
        return None
        
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
        
    metrics = dict(row)
    
    input_tokens = metrics.get('input_tokens', 0) or 0
    output_tokens = metrics.get('output_tokens', 0) or 0
    cache_read_tokens = metrics.get('cache_read_tokens', 0) or 0
    cache_write_tokens = metrics.get('cache_write_tokens', 0) or 0
    
    metrics['total_tokens'] = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
    
    started_at = metrics.get('started_at')
    ended_at = metrics.get('ended_at')
    if started_at and ended_at:
        try:
            start_dt = datetime.fromisoformat(started_at)
            end_dt = datetime.fromisoformat(ended_at)
            metrics['elapsed_seconds'] = (end_dt - start_dt).total_seconds()
        except Exception:
            metrics['elapsed_seconds'] = 0.0
    else:
        metrics['elapsed_seconds'] = 0.0
        
    model_config_str = metrics.get('model_config')
    metrics['reasoning_effort'] = None
    if model_config_str:
        try:
            model_config = json.loads(model_config_str)
            if 'reasoning_config' in model_config and isinstance(model_config['reasoning_config'], dict):
                metrics['reasoning_effort'] = model_config['reasoning_config'].get('effort')
        except json.JSONDecodeError:
            pass
            
    return metrics
