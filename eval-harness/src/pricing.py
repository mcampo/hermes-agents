# Pricing in USD per 1M tokens
DEEPSEEK_V4_FLASH_INPUT = 0.14
DEEPSEEK_V4_FLASH_OUTPUT = 0.28
DEEPSEEK_V4_FLASH_CACHE_READ = 0.014

def calculate_deepseek_cost(model: str, metrics: dict) -> float:
    input_tokens = metrics.get('input_tokens', 0) or 0
    output_tokens = metrics.get('output_tokens', 0) or 0
    cache_read_tokens = metrics.get('cache_read_tokens', 0) or 0
    
    if "flash" in model.lower():
        input_cost = (input_tokens / 1_000_000) * DEEPSEEK_V4_FLASH_INPUT
        output_cost = (output_tokens / 1_000_000) * DEEPSEEK_V4_FLASH_OUTPUT
        cache_cost = (cache_read_tokens / 1_000_000) * DEEPSEEK_V4_FLASH_CACHE_READ
        return input_cost + output_cost + cache_cost
    
    return 0.0
