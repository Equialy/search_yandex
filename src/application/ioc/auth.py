from uuid import UUID
from dishka import Provider, Scope, provide
from fastapi import HTTPException, Request, status

from src.application.services.auth.service import AuthService
from src.application.uow import UnitOfWorkProtocol
from src.application.use_cases.login_user import LoginUserUseCase
from src.application.use_cases.registre_user import RegisterUserUseCase
from src.infrastructure.database.models.users import User, UserRole


class AuthProvider(Provider):
    auth_service = provide(AuthService, scope=Scope.APP)
    register_use_case = provide(RegisterUserUseCase, scope=Scope.REQUEST)
    login_use_case = provide(LoginUserUseCase, scope=Scope.REQUEST)

    @provide(scope=Scope.REQUEST)
    async def get_current_user(
        self,
        request: Request,
        uow: UnitOfWorkProtocol,
        auth_service: AuthService,
    ) -> User:
        """Извлекает токен из Cookie или Bearer Header, проверяет админа и отдает User."""
        token = request.cookies.get("access_token")

        if not token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Требуется авторизация"
            )

        payload = auth_service.decode_token(token)
        if not payload or "sub" not in payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Токен недействителен или срок его действия истек"
            )

        try:
            user_id = UUID(payload["sub"])
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Некорректный идентификатор пользователя в токене"
            )

        async with uow:
            user = await uow.users.get_by_id(user_id)
            if not user or not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Пользователь не найден или заблокирован"
                )

            if user.role != UserRole.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Доступ запрещен: требуются права администратора"
                )

            return user