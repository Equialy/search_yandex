# src/application/use_cases/register_user.py

from fastapi import HTTPException, status
from src.application.services.auth.service import AuthService
from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.database.models.users import User, UserRole


class RegisterUserUseCase:
    def __init__(self, uow: UnitOfWorkProtocol, auth_service: AuthService):
        self._uow = uow
        self._auth = auth_service

    async def execute(self,  username: str, raw_password: str) -> tuple[User, str]:
        username_clean = username.strip()

        async with self._uow as uow:

            if await uow.users.get_by_username(username_clean):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Пользователь с таким username уже существует"
                )

            hashed_pwd = self._auth.hash_password(raw_password)

            user = User(
                username=username_clean,
                password=hashed_pwd,
                role=UserRole.ADMIN,
                is_active=True
            )
            await uow.users.add(user)

        token = self._auth.create_access_token(user.id, user.role.value)
        return user, token