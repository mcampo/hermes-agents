import argparse
import time
from datetime import datetime
from pathlib import Path
import sys

# Add src to python path so we can import modules
sys.path.insert(0, str(Path(__file__).parent))

from config import load_config, load_api_key, load_sheets_config
from task_registry import discover_tasks, filter_tasks, list_tasks
from executor import run_hermes
from metrics import get_session_metrics
from cost_tracker import create_cost_tracker
from session_logger import dump_session
from results import save_result_csv
from sheets import append_result_to_sheet

def main():
    parser = argparse.ArgumentParser(description="Evaluation Harness")
    parser.add_argument("--models", type=str, help="Substring filter for model names")
    parser.add_argument("--tasks", type=str, help="Comma-separated list of task names to run")
    parser.add_argument("--runs", type=int, help="Iteration count")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Print plan and exit")
    parser.add_argument("--list-tasks", action="store_true", help="List available tasks and exit")
    
    args = parser.parse_args()
    
    tasks_dir = Path(__file__).parent.parent / "tasks"
    all_tasks = discover_tasks(tasks_dir)
    
    if args.list_tasks:
        print(list_tasks(all_tasks))
        return
        
    task_names = [t.strip() for t in args.tasks.split(",")] if args.tasks else []
    selected_tasks = filter_tasks(all_tasks, task_names) if task_names else all_tasks
    
    config = load_config()
    model_configs = config.get("models", [])
    if args.models:
        model_configs = [m for m in model_configs if args.models in m.get("model", "")]
        
    runs = args.runs if args.runs is not None else config.get("runs", 1)
    eval_profile = config.get("eval_profile", "eval")
    
    if args.dry_run:
        print("Dry Run Plan:")
        print(f"Tasks: {[t.name for t in selected_tasks]}")
        print(f"Models: {[m.get('model') for m in model_configs]}")
        print(f"Runs: {runs}")
        print(f"Total executions: {len(selected_tasks) * len(model_configs) * runs}")
        return
        
    results_csv_path = Path(__file__).parent.parent / "results" / "eval_results.csv"
    sessions_dir = Path(__file__).parent.parent / "results" / "sessions"
    
    # Factory cache for trackers
    trackers = {}
    for m in model_configs:
        provider = m.get("provider", "")
        if provider not in trackers:
            api_key = load_api_key(provider)
            trackers[provider] = create_cost_tracker(provider, api_key)
            
    for task in selected_tasks:
        for run_num in range(1, runs + 1):
            for m in model_configs:
                model_name = m.get("model", "")
                provider = m.get("provider", "")
                reasoning_effort = m.get("reasoning_effort")
                config_name = f"{model_name} ({reasoning_effort})" if reasoning_effort else model_name
                
                print(f"Running task={task.name} run={run_num} model={config_name}")
                
                task.reset()
                
                tracker = trackers.get(provider)
                if tracker:
                    tracker.snapshot_before()
                
                timestamp = time.time()
                dt_iso = datetime.now().isoformat()
                
                timeout = task.timeout if task.timeout else args.timeout
                
                exec_result = run_hermes(
                    model=model_name,
                    provider=provider,
                    reasoning_effort=reasoning_effort,
                    prompt=task.prompt,
                    skills=task.skills,
                    profile=eval_profile,
                    timeout=timeout
                )
                
                print(f"  Execution result: {exec_result}")
                
                session_id = exec_result.get("session_id")
                if not session_id:
                    print(f"  Failed to extract session ID. Error: {exec_result.get('error')}")
                    continue
                    
                if tracker and tracker.needs_post_run_wait():
                    print("  Waiting for cost reconciliation...")
                    time.sleep(5)
                
                metrics = get_session_metrics(eval_profile, session_id)
                if not metrics:
                    metrics = {}
                    
                if tracker:
                    tracker.snapshot_after()
                    actual_cost = tracker.calculate_cost(model_name, metrics)
                else:
                    actual_cost = 0.0
                    
                val_result = task.validate(exec_result.get("output", ""))
                
                transcript_path = dump_session(session_id, sessions_dir, eval_profile)
                
                row = {
                    "timestamp": timestamp,
                    "datetime": dt_iso,
                    "provider": provider,
                    "model": model_name,
                    "reasoning_effort": reasoning_effort,
                    "config_name": config_name,
                    "task": task.name,
                    "run_number": run_num,
                    "session_id": session_id,
                    "input_tokens": metrics.get("input_tokens", 0),
                    "output_tokens": metrics.get("output_tokens", 0),
                    "cache_read_tokens": metrics.get("cache_read_tokens", 0),
                    "cache_write_tokens": metrics.get("cache_write_tokens", 0),
                    "reasoning_tokens": metrics.get("reasoning_tokens", 0),
                    "total_tokens": metrics.get("total_tokens", 0),
                    "api_calls": metrics.get("api_call_count", 0),
                    "tool_calls": metrics.get("tool_call_count", 0),
                    "message_count": metrics.get("message_count", 0),
                    "elapsed_seconds": metrics.get("elapsed_seconds", 0.0),
                    "estimated_cost": metrics.get("estimated_cost_usd", 0.0),
                    "actual_cost": actual_cost,
                    "validation_score": val_result.get("score", 0.0),
                    "validation_details": val_result.get("details", []),
                    "agent_output": exec_result.get("output", ""),
                    "transcript_path": str(transcript_path)
                }
                
                save_result_csv(row, results_csv_path)
                
                sheets_config = load_sheets_config()
                if sheets_config:
                    append_result_to_sheet(
                        row=row,
                        spreadsheet_id=sheets_config.get("spreadsheet_id", ""),
                        sheet_name=sheets_config.get("sheet_name", ""),
                        token_path=sheets_config.get("token_path", "")
                    )
                
                print(f"  Done. Session: {session_id} Score: {row['validation_score']}")

if __name__ == "__main__":
    main()
