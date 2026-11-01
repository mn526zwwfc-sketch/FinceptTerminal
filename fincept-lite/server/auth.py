"""Identidad: réplica de las rutas /user/* de api.fincept.in.

Contrato observado en el cliente C++ (auth/AuthApi.cpp, auth/AuthManager.cpp,
network/http/HttpClient.cpp) y en el OpenAPI público del servidor:

* Registro → OTP de 6 dígitos → verify-otp → api_key + session_token.
* Login devuelve {"success":true,"data":{api_key, session_token, ...}} o
  variantes {"active_session":true} (otro dispositivo) / {"mfa_required":true}.
* Los fallos de negocio viajan con HTTP 200 y {"success":false,"message":...}
  (el cliente muestra el mensaje tal cual). 422 = errores Pydantic {"detail":[...]}.
* Peticiones autenticadas: cabecera X-API-Key (+ X-Session-Token). El servicio
  Go "finceptgo" bajo /v1 acepta Authorization: Bearer <api_key>.
* 401 → el SessionGuard del terminal cierra la sesión automáticamente.
* Cada endpoint de pago descuenta créditos; sin saldo → error insufficient_credits.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from .config import settings
from .db import get_db

router = APIRouter()

MAX_LOGIN_ATTEMPTS = 3
LOCK_SECONDS = 120
OTP_TTL = 600
RATE_LIMIT = 240  # peticiones / minuto por api_key
RATE_WINDOW = 60


# ── utilidades ───────────────────────────────────────────────────────────────

def ok(data: dict | list | None = None, message: str = "OK") -> dict:
    return {"success": True, "message": message, "data": data if data is not None else {}}


def fail(message: str, **extra) -> dict:
    return {"success": False, "message": message, **extra}


def hash_password(password: str, salt: str) -> str:
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()


def new_api_key() -> str:
    return "fk_user_" + secrets.token_urlsafe(32)


def new_otp() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def public_profile(u: dict) -> dict:
    return {
        "id": u["id"],
        "username": u["username"],
        "email": u["email"],
        "account_type": u["account_type"],
        "credit_balance": round(u["credit_balance"], 2),
        "credits_expire_at": None,
        "is_verified": bool(u["is_verified"]),
        "is_admin": bool(u["is_admin"]),
        "mfa_enabled": bool(u["mfa_enabled"]),
        "phone": u["phone"],
        "country": u["country"],
        "country_code": u["country_code"],
        "created_at": _iso(u["created_at"]),
        "last_login_at": _iso(u["last_login_at"]),
        "rate_limit": _rate_info(u["api_key"]),
    }


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


_hits: dict[str, deque] = defaultdict(deque)


def _rate_info(api_key: str | None) -> dict:
    q = _hits.get(api_key or "", deque())
    now = time.time()
    used = sum(1 for t in q if t > now - RATE_WINDOW)
    return {
        "limit": RATE_LIMIT,
        "remaining": max(0, RATE_LIMIT - used),
        "reset_at": int(now + RATE_WINDOW),
        "window_seconds": RATE_WINDOW,
        "concurrent_limit": 8,
    }


def _rate_check(api_key: str) -> None:
    now = time.time()
    q = _hits[api_key]
    while q and q[0] < now - RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={"success": False, "error": "rate_limit_exceeded", "message": "Too many requests"},
        )
    q.append(now)


# ── dependencias de autenticación ───────────────────────────────────────────

def user_from_api_key(api_key: str | None) -> dict | None:
    if not api_key:
        return None
    return get_db().one("SELECT * FROM users WHERE api_key=?", (api_key,))


def session_valid(user_id: int, token: str) -> bool:
    row = get_db().one("SELECT active FROM sessions WHERE token=? AND user_id=?", (token, user_id))
    return bool(row and row["active"])


async def require_auth(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_session_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    api_key = x_api_key
    if not api_key and authorization and authorization.lower().startswith("bearer "):
        api_key = authorization[7:].strip()
    user = user_from_api_key(api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    # Igual que el servidor real: si se envía un token de sesión debe seguir
    # activo (si otro dispositivo hizo force_login, este recibe 401).
    if x_session_token and not session_valid(user["id"], x_session_token):
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    _rate_check(api_key)
    request.state.user = user
    request.state.session_token = x_session_token
    return user


class InsufficientCredits(Exception):
    def __init__(self, needed: float, balance: float) -> None:
        self.needed, self.balance = needed, balance


def charge(user: dict, endpoint: str, credits: float) -> None:
    """Descuenta créditos de forma atómica y registra el uso (GET /user/usage)."""
    if credits <= 0:
        get_db().execute(
            "INSERT INTO usage(user_id, at, endpoint, credits) VALUES (?,?,?,0)", (user["id"], time.time(), endpoint)
        )
        return
    with get_db().transaction() as conn:
        row = conn.execute("SELECT credit_balance FROM users WHERE id=?", (user["id"],)).fetchone()
        balance = row["credit_balance"]
        if balance < credits:
            raise InsufficientCredits(credits, balance)
        conn.execute("UPDATE users SET credit_balance=credit_balance-? WHERE id=?", (credits, user["id"]))
        conn.execute(
            "INSERT INTO usage(user_id, at, endpoint, credits) VALUES (?,?,?,?)",
            (user["id"], time.time(), endpoint, credits),
        )


def refund(user: dict, endpoint: str, credits: float) -> None:
    get_db().execute("UPDATE users SET credit_balance=credit_balance+? WHERE id=?", (credits, user["id"]))
    get_db().execute(
        "INSERT INTO usage(user_id, at, endpoint, credits) VALUES (?,?,?,?)",
        (user["id"], time.time(), endpoint + " (refund)", -credits),
    )


def insufficient_credits_response(exc: InsufficientCredits) -> JSONResponse:
    return JSONResponse(
        status_code=402,
        content={
            "success": False,
            "error": "insufficient_credits",
            "message": f"This request needs {exc.needed:g} credits; your balance is {exc.balance:.2f}.",
            "hint": "Top up credits from Profile → Plans.",
        },
    )


# ── modelos de petición (Pydantic → 422 {"detail":[...]} como FastAPI) ──────

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    phone: str = Field(default="", max_length=20)
    country_code: str = Field(default="", max_length=6)
    country: str = Field(default="", max_length=60)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    force_login: bool = False


class OtpRequest(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6)


class EmailOnly(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=128)


class ProfileUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_]+$")
    phone: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=60)
    country_code: str | None = Field(default=None, max_length=6)


# ── lógica compartida ───────────────────────────────────────────────────────

def _issue_otp(user_id: int) -> str:
    otp = new_otp()
    get_db().execute(
        "UPDATE users SET otp=?, otp_expires=?, otp_attempts=0 WHERE id=?", (otp, time.time() + OTP_TTL, user_id)
    )
    # El servidor real envía el código por email. En modo dev lo imprimimos.
    print(f"[auth] OTP for user {user_id}: {otp}", flush=True)
    return otp


def _check_otp(user: dict, otp: str) -> str | None:
    """Devuelve None si el OTP es válido; si no, el mensaje de error."""
    if not user.get("otp") or user["otp_expires"] < time.time():
        return "Your verification code has expired. Please request a new one."
    if not hmac.compare_digest(user["otp"], otp):
        attempts = user["otp_attempts"] + 1
        get_db().execute("UPDATE users SET otp_attempts=? WHERE id=?", (attempts, user["id"]))
        left = max(0, 3 - attempts)
        if left == 0:
            get_db().execute("UPDATE users SET otp=NULL WHERE id=?", (user["id"],))
            return "Too many incorrect codes. Please request a new verification code."
        return f"Incorrect verification code. You have {left} attempt(s) remaining."
    get_db().execute("UPDATE users SET otp=NULL, otp_attempts=0 WHERE id=?", (user["id"],))
    return None


def _start_session(user: dict, request: Request) -> dict:
    db = get_db()
    now = time.time()
    token = secrets.token_urlsafe(32)
    # Una sola sesión activa por usuario (el terminal muestra "already logged in
    # on another device" y ofrece force_login).
    db.execute("UPDATE sessions SET active=0 WHERE user_id=?", (user["id"],))
    db.execute(
        "INSERT INTO sessions(token, user_id, created_at, last_seen, active, user_agent) VALUES (?,?,?,?,1,?)",
        (token, user["id"], now, now, request.headers.get("user-agent", "")[:200]),
    )
    db.execute("UPDATE users SET last_login_at=?, failed_attempts=0, locked_until=0 WHERE id=?", (now, user["id"]))
    db.execute(
        "INSERT INTO login_history(user_id, at, ip, user_agent, success) VALUES (?,?,?,?,1)",
        (user["id"], now, request.client.host if request.client else "", request.headers.get("user-agent", "")[:200]),
    )
    fresh = db.one("SELECT * FROM users WHERE id=?", (user["id"],))
    return {"api_key": fresh["api_key"], "session_token": token, "user": public_profile(fresh)}


def create_user(username: str, email: str, password: str, verified: bool = False, **extra) -> dict:
    salt = secrets.token_hex(16)
    get_db().execute(
        "INSERT INTO users(username, email, password_hash, salt, phone, country_code, country, is_verified,"
        " credit_balance, api_key, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            username,
            email.lower(),
            hash_password(password, salt),
            salt,
            extra.get("phone", ""),
            extra.get("country_code", ""),
            extra.get("country", ""),
            1 if verified else 0,
            settings.free_credits,
            new_api_key(),
            time.time(),
        ),
    )
    return get_db().one("SELECT * FROM users WHERE email=?", (email.lower(),))


def ensure_demo_user() -> None:
    if not settings.dev_mode:
        return
    if not get_db().one("SELECT id FROM users WHERE email=?", ("demo@example.com",)):
        create_user("demo", "demo@example.com", "demo12345", verified=True, country="ES", country_code="+34")


# ── rutas no autenticadas ───────────────────────────────────────────────────

@router.post("/user/register")
async def register(req: RegisterRequest):
    db = get_db()
    if db.one("SELECT id FROM users WHERE email=?", (req.email.lower(),)):
        return fail("An account with this email already exists.")
    if db.one("SELECT id FROM users WHERE username=?", (req.username,)):
        return fail("This username is already taken.")
    user = create_user(req.username, req.email, req.password, **req.model_dump(exclude={"username", "email", "password"}))
    otp = _issue_otp(user["id"])
    data = {"email": user["email"], "otp_sent": True}
    if settings.dev_mode:
        data["dev_otp"] = otp  # SOLO en desarrollo: en producción va por email
    return ok(data, "Registration successful. Check your email for the verification code.")


@router.post("/user/resend-otp")
async def resend_otp(req: EmailOnly):
    user = get_db().one("SELECT * FROM users WHERE email=?", (req.email.lower(),))
    if not user:
        return fail("Account not found. Please check your email.")
    otp = _issue_otp(user["id"])
    return ok({"dev_otp": otp} if settings.dev_mode else {}, "A new verification code has been sent.")


@router.post("/user/verify-otp")
async def verify_otp(req: OtpRequest, request: Request):
    user = get_db().one("SELECT * FROM users WHERE email=?", (req.email.lower(),))
    if not user:
        return fail("Account not found. Please check your email.")
    err = _check_otp(user, req.otp)
    if err:
        return fail(err)
    get_db().execute("UPDATE users SET is_verified=1 WHERE id=?", (user["id"],))
    return ok(_start_session(user, request), "Email verified. Welcome to Fincept!")


@router.post("/user/login")
async def login(req: LoginRequest, request: Request):
    db = get_db()
    user = db.one("SELECT * FROM users WHERE email=?", (req.email.lower(),))
    if not user:
        return fail("Account not found. Please check your email.")
    now = time.time()
    if user["locked_until"] > now:
        mins = max(1, round((user["locked_until"] - now) / 60))
        return fail(f"Too many failed attempts — please try again in {mins} minute(s).")
    if not hmac.compare_digest(hash_password(req.password, user["salt"]), user["password_hash"]):
        attempts = user["failed_attempts"] + 1
        db.execute(
            "INSERT INTO login_history(user_id, at, ip, user_agent, success) VALUES (?,?,?,?,0)",
            (user["id"], now, request.client.host if request.client else "", request.headers.get("user-agent", "")[:200]),
        )
        if attempts >= MAX_LOGIN_ATTEMPTS:
            db.execute("UPDATE users SET failed_attempts=0, locked_until=? WHERE id=?", (now + LOCK_SECONDS, user["id"]))
            return fail("Too many failed attempts — please try again in 2 minutes.")
        db.execute("UPDATE users SET failed_attempts=? WHERE id=?", (attempts, user["id"]))
        return fail(f"Incorrect password. You have {MAX_LOGIN_ATTEMPTS - attempts} attempt(s) remaining.")
    if not user["is_verified"]:
        otp = _issue_otp(user["id"])
        extra = {"dev_otp": otp} if settings.dev_mode else {}
        return fail("Your account is not verified yet. We sent you a new code.", needs_verification=True, **extra)
    active = db.one("SELECT token FROM sessions WHERE user_id=? AND active=1", (user["id"],))
    if active and not req.force_login:
        return ok({"active_session": True, "message": "You are already logged in on another device."})
    if user["mfa_enabled"]:
        otp = _issue_otp(user["id"])
        return ok({"mfa_required": True, **({"dev_otp": otp} if settings.dev_mode else {})}, "MFA code sent.")
    return ok(_start_session(user, request), "Login successful")


@router.post("/user/verify-mfa")
async def verify_mfa(req: OtpRequest, request: Request):
    user = get_db().one("SELECT * FROM users WHERE email=?", (req.email.lower(),))
    if not user:
        return fail("Account not found. Please check your email.")
    err = _check_otp(user, req.otp)
    return fail(err) if err else ok(_start_session(user, request), "Login successful")


@router.post("/user/forgot-password")
async def forgot_password(req: EmailOnly):
    user = get_db().one("SELECT * FROM users WHERE email=?", (req.email.lower(),))
    data = {}
    if user:
        otp = _issue_otp(user["id"])
        if settings.dev_mode:
            data["dev_otp"] = otp
    # Respuesta idéntica exista o no la cuenta (no revela emails).
    return ok(data, "If the account exists, a reset code has been sent.")


@router.post("/user/reset-password")
async def reset_password(req: ResetPasswordRequest):
    user = get_db().one("SELECT * FROM users WHERE email=?", (req.email.lower(),))
    if not user:
        return fail("Account not found. Please check your email.")
    err = _check_otp(user, req.otp)
    if err:
        return fail(err)
    salt = secrets.token_hex(16)
    get_db().execute(
        "UPDATE users SET password_hash=?, salt=? WHERE id=?", (hash_password(req.new_password, salt), salt, user["id"])
    )
    get_db().execute("UPDATE sessions SET active=0 WHERE user_id=?", (user["id"],))
    return ok({}, "Password updated. Please log in again.")


# ── rutas autenticadas ──────────────────────────────────────────────────────

@router.get("/auth/validate")
async def validate_key(user: dict = Depends(require_auth)):
    return ok({"valid": True, "user_id": user["id"], "account_type": user["account_type"]})


@router.post("/user/logout")
async def logout(request: Request, user: dict = Depends(require_auth)):
    token = request.state.session_token
    if token:
        get_db().execute("UPDATE sessions SET active=0 WHERE token=?", (token,))
    else:
        get_db().execute("UPDATE sessions SET active=0 WHERE user_id=?", (user["id"],))
    return ok({}, "Logged out")


@router.get("/user/session-pulse")
async def session_pulse(request: Request, user: dict = Depends(require_auth)):
    token = request.state.session_token
    if not token:
        raise HTTPException(status_code=401, detail="Session token required")
    get_db().execute("UPDATE sessions SET last_seen=? WHERE token=?", (time.time(), token))
    return ok({"alive": True, "credit_balance": round(user["credit_balance"], 2)})


@router.post("/user/validate-session")
async def validate_session(request: Request, user: dict = Depends(require_auth)):
    token = request.state.session_token
    return ok({"valid": bool(token and session_valid(user["id"], token))})


@router.get("/user/profile")
async def get_profile(user: dict = Depends(require_auth)):
    return ok(public_profile(user))


@router.put("/user/profile")
async def update_profile(body: ProfileUpdate, user: dict = Depends(require_auth)):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if "username" in fields and get_db().one(
        "SELECT id FROM users WHERE username=? AND id<>?", (fields["username"], user["id"])
    ):
        return fail("This username is already taken.")
    for k, v in fields.items():
        get_db().execute(f"UPDATE users SET {k}=? WHERE id=?", (v, user["id"]))  # k viene del modelo, no del cliente
    return ok(public_profile(get_db().one("SELECT * FROM users WHERE id=?", (user["id"],))), "Profile updated")


@router.post("/user/regenerate-api-key")
async def regenerate_api_key(user: dict = Depends(require_auth)):
    key = new_api_key()
    get_db().execute("UPDATE users SET api_key=? WHERE id=?", (key, user["id"]))
    return ok({"api_key": key}, "API key regenerated. Update every client that used the old one.")


@router.get("/user/usage")
async def get_usage(user: dict = Depends(require_auth)):
    rows = get_db().all(
        "SELECT endpoint, COUNT(*) AS calls, SUM(credits) AS credits FROM usage WHERE user_id=?"
        " GROUP BY endpoint ORDER BY credits DESC",
        (user["id"],),
    )
    recent = get_db().all(
        "SELECT at, endpoint, credits FROM usage WHERE user_id=? ORDER BY id DESC LIMIT 25", (user["id"],)
    )
    for r in recent:
        r["at"] = _iso(r["at"])
    return ok({"credit_balance": round(user["credit_balance"], 2), "by_endpoint": rows, "recent": recent})


@router.get("/user/login-history")
async def login_history(user: dict = Depends(require_auth)):
    rows = get_db().all(
        "SELECT at, ip, user_agent, success FROM login_history WHERE user_id=? ORDER BY id DESC LIMIT 20",
        (user["id"],),
    )
    for r in rows:
        r["at"] = _iso(r["at"])
        r["success"] = bool(r["success"])
    return ok(rows)


@router.post("/user/mfa/enable")
async def mfa_enable(user: dict = Depends(require_auth)):
    get_db().execute("UPDATE users SET mfa_enabled=1 WHERE id=?", (user["id"],))
    return ok({"mfa_enabled": True}, "MFA enabled: next logins require an email code.")


@router.post("/user/mfa/disable")
async def mfa_disable(user: dict = Depends(require_auth)):
    get_db().execute("UPDATE users SET mfa_enabled=0 WHERE id=?", (user["id"],))
    return ok({"mfa_enabled": False}, "MFA disabled")


@router.get("/cashfree/plans")
async def plans():
    # Desde 4.5.1 el catálogo del terminal abierto son dos planes: free y pro.
    return ok(
        [
            {"plan_id": "free", "name": "Free", "is_free": True, "price_usd": 0, "currency": "USD",
             "credits": int(settings.free_credits), "support_type": "community", "validity_days": 0,
             "features": ["Market data", "News", "Paper trading", "MCP server"]},
            {"plan_id": "pro", "name": "Pro", "is_free": False, "price_usd": 10, "currency": "USD",
             "credits": 2000, "support_type": "priority", "validity_days": 30,
             "features": ["Monthly cloud credits", "Higher API limits", "Priority support"]},
        ]
    )
