from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
import jwt
from passlib.context import CryptContext

from src.config.settings import settings

# Контекст для хеширования паролей через bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:

    @staticmethod
    def hash_password(password: str) -> str:
        """Хеширование пароля"""
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Проверка совпадения пароля"""
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def create_access_token(user_id: UUID, role: str) -> str:
        """Генерация JWT токена"""
        now = datetime.now(timezone.utc)
        expire = now + timedelta(minutes=settings.jwt.access_token_expire_minutes)

        payload = {
            "sub": str(user_id),
            "role": role,
            "exp": expire,
            "iat": now,
        }
        return jwt.encode(payload, settings.jwt.secret_key, algorithm=settings.jwt.algorithm)

    @staticmethod
    def decode_token(token: str) -> Optional[dict]:
        """Расшифровка и проверка валидности токена"""
        try:
            payload = jwt.decode(
                token,
                settings.jwt.secret_key,
                algorithms=[settings.jwt.algorithm]
            )
            return payload
        except jwt.PyJWTError:
            return None