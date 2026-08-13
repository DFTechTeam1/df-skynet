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

LOCAL_MYSQL_USERNAME = quote_plus(os.getenv("LOCAL_MYSQL_USERNAME", ""))
LOCAL_MYSQL_PASSWORD = quote_plus(os.getenv("LOCAL_MYSQL_PASSWORD", ""))
LOCAL_MYSQL_DATABASE = quote_plus(os.getenv("LOCAL_MYSQL_DATABASE", ""))
LOCAL_MYSQL_HOST = os.getenv("LOCAL_MYSQL_HOST", "")
LOCAL_MYSQL_PORT = os.getenv("LOCAL_MYSQL_PORT", "")
VPS_MYSQL_USERNAME = quote_plus(os.getenv("VPS_MYSQL_USERNAME", ""))
VPS_MYSQL_PASSWORD = quote_plus(os.getenv("VPS_MYSQL_PASSWORD", ""))
VPS_MYSQL_DATABASE = quote_plus(os.getenv("VPS_MYSQL_DATABASE", ""))
VPS_MYSQL_HOST = os.getenv("VPS_MYSQL_HOST", "")
VPS_MYSQL_PORT = os.getenv("VPS_MYSQL_PORT", "")
