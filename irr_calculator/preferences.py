from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import keyring

from .database import app_data_dir

SERVICE = "IRRCalculator/FinMind"


def preferences_path() -> Path:
    return app_data_dir() / "preferences.json"


def load_preferences() -> dict[str, Any]:
    path = preferences_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_preferences(values: dict[str, Any]) -> None:
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2), encoding="utf-8")


def get_finmind_token() -> str:
    return keyring.get_password(SERVICE, "token") or ""


def save_finmind_token(token: str) -> None:
    if token.strip():
        keyring.set_password(SERVICE, "token", token.strip())
    else:
        try:
            keyring.delete_password(SERVICE, "token")
        except keyring.errors.PasswordDeleteError:
            pass
