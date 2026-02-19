import logging
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

# Pricing constants per 1 Million tokens (USD)
# Source: https://cloud.google.com/vertex-ai/pricing
# Updated: Feb 2026

class ModelPricing:
    # Gemini 2.5 Flash
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_5_FLASH_INPUT_TEXT = 0.30
    GEMINI_2_5_FLASH_OUTPUT = 2.50
    
    # Gemini 2.5 Pro (<= 200K context window assumed for single invoices)
    # If context > 200K, input is $2.50 and output is $15.00
    GEMINI_2_5_PRO = "gemini-2.5-pro"
    GEMINI_2_5_PRO_INPUT = 1.25  # Text/Image all same
    GEMINI_2_5_PRO_OUTPUT = 10.00


def calculate_cost(model_name: str, usage_metadata: dict) -> float:
    """
    Calculate the estimated cost of a Vertex AI call based on token usage.
    
    Args:
        model_name: Name of the model used (e.g. "gemini-2.5-flash-001")
        usage_metadata: Dictionary containing 'prompt_token_count' and 'candidates_token_count'
                       (and optionally 'total_token_count')
    
    Returns:
        float: Estimated cost in USD
    """
    if not usage_metadata:
        return 0.0
        
    prompt_tokens = usage_metadata.get("prompt_token_count", 0)
    response_tokens = usage_metadata.get("candidates_token_count", 0)
    
    # Normalize model name for matching (ignoring version suffixes like -001)
    model_base = model_name.lower()
    
    cost = 0.0
    
    if "gemini-2.5-flash" in model_base:
        # Note: We assume mostly text/image input here. 
        # Deep inspection of modality specific tokens isn't always available in basic usage metadata
        # so we use the standard text/image rate ($0.30/1M) as the baseline.
        input_cost = (prompt_tokens / 1_000_000) * ModelPricing.GEMINI_2_5_FLASH_INPUT_TEXT
        output_cost = (response_tokens / 1_000_000) * ModelPricing.GEMINI_2_5_FLASH_OUTPUT
        cost = input_cost + output_cost
        
    elif "gemini-2.5-pro" in model_base:
        # Assuming <= 200K context tier for standard invoices
        # If prompt_tokens > 200,000, we should use the higher tier
        
        input_rate = ModelPricing.GEMINI_2_5_PRO_INPUT
        output_rate = ModelPricing.GEMINI_2_5_PRO_OUTPUT
        
        if prompt_tokens > 200_000:
            input_rate = 2.50
            output_rate = 15.00
            
        input_cost = (prompt_tokens / 1_000_000) * input_rate
        output_cost = (response_tokens / 1_000_000) * output_rate
        cost = input_cost + output_cost
        
    # Fallback for older/other models (using approximate Flash 1.5 rates as safe default or 0)
    else:
        # Default to 0 if unknown to avoid misleading costs
        pass
        
    
    return round(cost, 6)

# Currency Conversion Constants
DEFAULT_USD_TO_ILS_RATE = 3.2
_cached_rate = None
_rate_expiry = None

def get_usd_to_ils_rate() -> float:
    """
    Fetches the live USD to ILS exchange rate using yfinance.
    Caches the rate for 1 hour. Falls back to DEFAULT_USD_TO_ILS_RATE on error.
    """
    global _cached_rate, _rate_expiry
    
    if _cached_rate and _rate_expiry and datetime.now() < _rate_expiry:
        return _cached_rate

    try:
        # Fetch data for "ILS=X" (USD to ILS)
        ticker = yf.Ticker("ILS=X")
        # Get the latest close price
        history = ticker.history(period="1d")
        if not history.empty:
            rate = history["Close"].iloc[-1]
            _cached_rate = rate
            _rate_expiry = datetime.now() + timedelta(hours=1)
            logger.info(f"Fetched live USD to ILS rate: {rate}")
            return rate
    except Exception as e:
        logger.warning(f"Failed to fetch live currency rate: {e}. Using default: {DEFAULT_USD_TO_ILS_RATE}")
    
    return DEFAULT_USD_TO_ILS_RATE

def calculate_cost_ils(usd_cost: float) -> float:
    """
    Converts USD cost to ILS using the current rate.
    """
    rate = get_usd_to_ils_rate()
    return round(usd_cost * rate, 4)
