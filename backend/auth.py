"""帳號：密碼雜湊與 JWT。"""

import os
from datetime import timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from models import SessionLocal, User, now

# ponytail: 預設密鑰只適合本機開發，要上線就設 SECRET_KEY 環境變數
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-not-for-production-please-set-SECRET_KEY")
ALGORITHM = "HS256"
TOKEN_TTL = timedelta(days=7)

bearer = HTTPBearer(auto_error=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_token(user_id: int) -> str:
    return jwt.encode(
        {"sub": str(user_id), "exp": now() + TOKEN_TTL}, SECRET_KEY, algorithm=ALGORITHM
    )


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "請先登入", headers={"WWW-Authenticate": "Bearer"}
    )
    if creds is None:
        raise unauthorized
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized
    if user is None:
        raise unauthorized
    return user
