import sqlite3
import json
from pathlib import Path

def dump_session(session_id: str, output_dir: Path, profile: str) -> Path:
    db_path = Path.home() / ".hermes" / "profiles" / profile / "state.db"
    if not db_path.exists():
        return Path("")
        
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
    rows = cursor.fetchall()
    conn.close()
    
    messages = []
    for row in rows:
        msg = dict(row)
        if 'tool_calls' in msg and msg['tool_calls']:
            try:
                msg['tool_calls'] = json.loads(msg['tool_calls'])
            except json.JSONDecodeError:
                pass
        messages.append(msg)
        
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{session_id}.json"
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(messages, f, indent=2)
        
    return out_path
