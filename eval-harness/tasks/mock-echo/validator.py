import json
from pathlib import Path

def validate(agent_output: str) -> dict:
    fixtures_path = Path(__file__).parent / "fixtures" / "expected.json"
    if not fixtures_path.exists():
        return {"score": 0.0, "details": ["expected.json not found"]}
        
    with open(fixtures_path, "r", encoding="utf-8") as f:
        expected = json.load(f)
        
    expected_phrase = expected.get("expected_output", "")
    
    if expected_phrase in agent_output:
        return {"score": 1.0, "details": ["Expected phrase found"]}
    else:
        return {"score": 0.0, "details": [f"Expected phrase '{expected_phrase}' not found in output"]}
