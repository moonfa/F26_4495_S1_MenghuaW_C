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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
