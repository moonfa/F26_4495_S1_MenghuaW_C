"""Single place for environment configuration."""
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./workbench.db")
OPENBB_PROVIDER = os.getenv("OPENBB_PROVIDER", "yfinance")
AI_PROVIDER = os.getenv("AI_PROVIDER", "mock").strip().lower()
AI_MODEL = os.getenv("AI_MODEL", "").strip()
AI_MODEL_BASELINE = os.getenv("AI_MODEL_BASELINE", "").strip()   # optional: stronger model for the one-off baseline
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

def _budget(raw: str):
    """AI_THINKING_BUDGET: integer token budget for model 'thinking'; 0 disables it; 'off' = do not send the setting."""
    raw = (raw or "").strip().lower()
    if raw in ("", "off", "none"):
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


AI_THINKING_BUDGET = _budget(os.getenv("AI_THINKING_BUDGET", "1024"))


def _models(raw: str) -> list[str]:
    return [m.strip() for m in (raw or "").split(",") if m.strip()]


AI_MODEL_FALLBACKS = _models(os.getenv("AI_MODEL_FALLBACKS", ""))   # tried in order when a model is out of quota
