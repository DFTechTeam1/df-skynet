import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parents[1]))
from utils import get_project_root

PROJECT_DIR = get_project_root()
DEFAULT_ENV_FILE = PROJECT_DIR / "env" / ".env.development"
env_file = Path(os.getenv("ENV_FILE", DEFAULT_ENV_FILE))

if not env_file.exists():
    raise FileNotFoundError(f"Environment file not found: {env_file}")

load_dotenv(dotenv_path=env_file, override=True)

DB_USERNAME = quote_plus(os.getenv("DB_USERNAME", ""))
DB_PASSWORD = quote_plus(os.getenv("DB_PASSWORD", ""))
DB_NAME = quote_plus(os.getenv("DB_NAME", ""))
DB_HOST = os.getenv("DB_HOST", "")
DB_PORT = os.getenv("DB_PORT", "")
DB_SYNC_URL = f"mysql+pymysql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
DB_ASYNC_URL = f"mysql+aiomysql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
JWT_PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY", "")
JWT_ISSUER = os.getenv("JWT_ISSUER", "")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "")
ERP_EMAIL = os.getenv("ERP_EMAIL", "")
ERP_PASSWORD = os.getenv("ERP_PASSWORD", "")
LOGIN_URL = os.getenv("LOGIN_URL", "")
BASE_URL = os.getenv("BASE_URL", "")
CORS_ALLOWED_ORIGINS = [o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MANAGEMENT_KEY = os.getenv("OPENROUTER_MANAGEMENT_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "")
REDIS_HOST = os.getenv("REDIS_HOST", "")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
