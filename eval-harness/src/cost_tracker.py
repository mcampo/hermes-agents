from abc import ABC, abstractmethod
from typing import Dict, Any

class CostTracker(ABC):
    @abstractmethod
    def snapshot_before(self) -> float: ...
    @abstractmethod
    def snapshot_after(self) -> float: ...
    @abstractmethod
    def calculate_cost(self, model: str, metrics: Dict[str, Any]) -> float: ...
    @abstractmethod
    def needs_post_run_wait(self) -> bool: ...

class OpenRouterCostTracker(CostTracker):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.before_usage = 0.0
        self.after_usage = 0.0
        
    def _fetch_usage(self) -> float:
        import requests
        try:
            response = requests.get(
                "https://openrouter.ai/api/v1/auth/key",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json().get("data", {})
                return float(data.get("usage", 0.0))
        except Exception:
            pass
        return 0.0
        
    def snapshot_before(self) -> float:
        self.before_usage = self._fetch_usage()
        return self.before_usage
        
    def snapshot_after(self) -> float:
        self.after_usage = self._fetch_usage()
        return self.after_usage
        
    def calculate_cost(self, model: str, metrics: Dict[str, Any]) -> float:
        return self.after_usage - self.before_usage
        
    def needs_post_run_wait(self) -> bool:
        return True

class DeepSeekCostTracker(CostTracker):
    def snapshot_before(self) -> float: return 0.0
    def snapshot_after(self) -> float: return 0.0
    
    def calculate_cost(self, model: str, metrics: Dict[str, Any]) -> float:
        return float(metrics.get("estimated_cost_usd", 0.0) or 0.0)
        
    def needs_post_run_wait(self) -> bool:
        return False

class NullCostTracker(CostTracker):
    def snapshot_before(self) -> float: return 0.0
    def snapshot_after(self) -> float: return 0.0
    def calculate_cost(self, model: str, metrics: Dict[str, Any]) -> float: return 0.0
    def needs_post_run_wait(self) -> bool: return False

def create_cost_tracker(provider: str, api_key: str = "") -> CostTracker:
    if provider.lower() == "openrouter":
        return OpenRouterCostTracker(api_key)
    elif provider.lower() == "deepseek":
        return DeepSeekCostTracker()
    else:
        return NullCostTracker()
