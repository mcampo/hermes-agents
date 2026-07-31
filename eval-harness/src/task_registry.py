import json
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import List, Callable, Dict, Any, Optional

@dataclass
class Task:
    name: str
    prompt: str
    skills: List[str]
    timeout: Optional[int]
    config: Dict[str, Any]
    reset: Callable[[], None]
    validate: Callable[[str], Dict[str, Any]]

    task_dir: Path
def load_module_from_path(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    raise ImportError(f"Could not load module {module_name} from {file_path}")

def discover_tasks(tasks_dir: Path) -> List[Task]:
    tasks = []
    if not tasks_dir.exists() or not tasks_dir.is_dir():
        return tasks

    for task_path in tasks_dir.iterdir():
        if not task_path.is_dir():
            continue

        config_path = task_path / "config.json"
        if not config_path.exists():
            continue

        with open(config_path, "r", encoding="utf-8") as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError:
                continue

        name = task_path.name
        prompt = config.get("prompt", "")
        skills = config.get("skills", [])
        timeout = config.get("timeout")

        reset_func = lambda: None
        reset_path = task_path / "reset.py"
        if reset_path.exists():
            try:
                mod = load_module_from_path(f"task_{name}_reset", reset_path)
                if hasattr(mod, "reset"):
                    reset_func = mod.reset
            except Exception as e:
                print(f"Error loading reset for task {name}: {e}")

        validate_func = lambda agent_output: {"score": 0.0, "details": ["Validator missing"]}
        validator_path = task_path / "validator.py"
        if validator_path.exists():
            try:
                mod = load_module_from_path(f"task_{name}_validator", validator_path)
                if hasattr(mod, "validate"):
                    validate_func = mod.validate
            except Exception as e:
                print(f"Error loading validator for task {name}: {e}")

        tasks.append(Task(
            name=name,
            prompt=prompt,
            skills=skills,
            timeout=timeout,
            config=config,
            reset=reset_func,
            validate=validate_func,
            task_dir=task_path.resolve(),
        ))

    return tasks

def filter_tasks(tasks: List[Task], names: List[str]) -> List[Task]:
    if not names:
        return tasks
    return [t for t in tasks if t.name in names]

def list_tasks(tasks: List[Task]) -> str:
    if not tasks:
        return "No tasks discovered."
    
    lines = []
    lines.append(f"{'Name':<20} | {'Prompt Preview':<60} | {'Skills Count'}")
    lines.append("-" * 20 + "-+-" + "-" * 60 + "-+-" + "-" * 12)
    
    for t in tasks:
        prompt_preview = t.prompt.replace('\n', ' ')
        if len(prompt_preview) > 57:
            prompt_preview = prompt_preview[:57] + "..."
        lines.append(f"{t.name:<20} | {prompt_preview:<60} | {len(t.skills)}")
        
    return "\n".join(lines)
