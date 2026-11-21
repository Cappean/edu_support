"""Trusted service boundary for the reference backend."""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def service_secret() -> str:
    configured = os.getenv("SERVICE_SECRET", "").strip()
    if configured:
        return configured
    path = Path(__file__).resolve().parents[2] / ".runtime" / "service-secret"
    path.parent.mkdir(exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    return path.read_text(encoding="utf-8").strip()
