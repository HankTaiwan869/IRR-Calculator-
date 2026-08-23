from __future__ import annotations

import keyring

SERVICE = "IRRCalculator/FinMind"


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
