from fastapi import HTTPException, status
from src.application.services.auth.service import AuthService
from src.application.uow import UnitOfWorkProtocol
from src.infrastructure.database.models.users import User, UserRole


class LoginUserUseCase:
    def __init__(self, uow: UnitOfWorkProtocol, auth_service: AuthService):
        self._uow = uow
        self._auth = auth_service

    async def execute(self, username: str, raw_password: str) -> tuple[User, str]:
        username_clean = username.strip().lower()

        async with self._uow as uow:
            user = await uow.users.get_by_username(username_clean)
            if not user or not self._auth.verify_password(raw_password, user.password):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Неверный username или пароль"
                )

            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Аккаунт заблокирован"
                )

            if user.role != UserRole.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Доступ разрешен только администраторам"
                )

        token = self._auth.create_access_token(user.id, user.role.value)
        return user, token