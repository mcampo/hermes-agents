import csv
from pathlib import Path
from typing import Dict, Any

FIELDNAMES = [
    "timestamp", "datetime", "provider", "model", "reasoning_effort", 
    "config_name", "task", "run_number", "session_id", "input_tokens", 
    "output_tokens", "cache_read_tokens", "cache_write_tokens", 
    "reasoning_tokens", "total_tokens", "api_calls", "tool_calls", 
    "message_count", "elapsed_seconds", "estimated_cost", "actual_cost", 
    "validation_score", "validation_details", "agent_output", "transcript_path"
]

def save_result_csv(row: Dict[str, Any], csv_path: Path):
    file_exists = csv_path.exists()
    
    with open(csv_path, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction='ignore')
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
