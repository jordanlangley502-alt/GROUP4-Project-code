import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .database import contextmanager_connection

ROLES = ("Owner", "Cashier", "Kitchen", "Delivery Person", "Supervisor")
bearer = HTTPBearer(auto_error=False)


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return f"scrypt${salt}${digest.hex()}"


def verify_password(password, stored):
    _, salt, expected = stored.split("$")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(actual.hex(), expected)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def lookup_user(database, token):
    with contextmanager_connection(database) as conn:
        user = conn.execute(
            "SELECT u.user_id,u.username,u.display_name,u.role FROM sessions s "
            "JOIN users u ON u.user_id=s.user_id WHERE s.token_hash=? AND s.expires_at>?",
            (token_hash(token), time.time()),
        ).fetchone()
        return dict(user) if user else None


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    user = lookup_user(request.app.state.database, credentials.credentials) if credentials else None
    if not user:
        raise HTTPException(401, "Sign in with a valid session.", headers={"WWW-Authenticate": "Bearer"})
    return user


def require(*roles):
    def check(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, "Your role cannot perform this action.")
        return user
    return check
