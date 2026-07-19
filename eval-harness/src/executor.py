import subprocess
import re
import time
from typing import Dict, Any, List, Optional

def run_hermes(model: str, provider: str, reasoning_effort: Optional[str], prompt: str, skills: List[str], profile: str, timeout: int) -> Dict[str, Any]:
    if reasoning_effort:
        config_cmd = ["hermes", "-p", profile, "config", "set", "agent.reasoning_effort", reasoning_effort]
        try:
            subprocess.run(config_cmd, check=True, capture_output=True)
        except Exception as e:
            err_msg = str(e)
            if hasattr(e, "stderr") and e.stderr:
                err_msg = e.stderr.decode('utf-8')
            return {
                "session_id": None,
                "output": "",
                "exit_code": getattr(e, "returncode", -1),
                "elapsed": 0.0,
                "error": f"Failed to set reasoning_effort: {err_msg}"
            }

    cmd = [
        "hermes", "-p", profile, "chat", "-q", prompt,
        "-m", model, "--provider", provider
    ]
    for skill in skills:
        cmd.extend(["-s", skill])
    
    cmd.append("-Q")
    
    result = {
        "session_id": None,
        "output": "",
        "exit_code": -1,
        "elapsed": 0.0,
        "error": None
    }
    
    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        result["output"] = proc.stdout.rstrip('\r\n') if proc.stdout else ""
        result["exit_code"] = proc.returncode
        result["error"] = proc.stderr if proc.returncode != 0 else None
        combined_output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        result["output"] = e.stdout.decode('utf-8').rstrip('\r\n') if e.stdout else ""
        result["error"] = "TimeoutExpired"
        combined_output = result["output"] + "\n" + (e.stderr.decode('utf-8') if e.stderr else "")
    except Exception as e:
        result["error"] = str(e)
        combined_output = ""
        
    result["elapsed"] = time.time() - start_time
    
    if combined_output:
        for line in combined_output.strip().split("\n"):
            line = line.strip()
            if line.startswith("session_id: "):
                result["session_id"] = line.replace("session_id: ", "").strip()
                break
        
        if not result["session_id"]:
            match = re.search(r'\b(\d{8}_\d{6}_[a-f0-9]{6})\b', combined_output)
            if match:
                result["session_id"] = match.group(1)
                
    return result
