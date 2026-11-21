import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
RUNTIME = ROOT / ".runtime"
RUNTIME.mkdir(exist_ok=True)


def local_secret(name: str, env: str) -> str:
    configured = os.getenv(env, "").strip()
    if configured:
        return configured
    path = RUNTIME / name
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    return path.read_text(encoding="utf-8").strip()


SECRET = local_secret("service-secret", "SERVICE_SECRET")
ADMIN_PASSWORD = local_secret("admin-password.txt", "ADMIN_PASSWORD")
REFERENCE_URL = os.getenv("REFERENCE_URL", "http://127.0.0.1:8001")
MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp")
DB_PATH = str(RUNTIME / "support.sqlite3")
CHECKPOINT_PATH = str(RUNTIME / "checkpoints.sqlite3")
