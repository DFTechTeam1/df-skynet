import logging
import os

from utils import get_project_root

BASE_FORMAT = "%(asctime)s %(levelname)s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
PROJECT_DIR = get_project_root()
ENV_TYPE = os.getenv("ENV_TYPE", "dev")
LOG_DIR = PROJECT_DIR / "log"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"server-{ENV_TYPE}.log"

logging.basicConfig(
    level=logging.INFO,
    format=BASE_FORMAT,
    datefmt=DATE_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, mode="a"),
    ],
)
