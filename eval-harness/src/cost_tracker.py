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
        self.before_balance = 0.0
        self.after_balance = 0.0
        
    def snapshot_before(self) -> float:
        self.before_balance = 0.0
        return self.before_balance
        
    def snapshot_after(self) -> float:
        self.after_balance = 0.0
        return self.after_balance
        
    def calculate_cost(self, model: str, metrics: Dict[str, Any]) -> float:
        return self.before_balance - self.after_balance
        
    def needs_post_run_wait(self) -> bool:
        return True

class DeepSeekCostTracker(CostTracker):
    def snapshot_before(self) -> float: return 0.0
    def snapshot_after(self) -> float: return 0.0
    
    def calculate_cost(self, model: str, metrics: Dict[str, Any]) -> float:
        from pricing import calculate_deepseek_cost
        return calculate_deepseek_cost(model, metrics)
        
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
