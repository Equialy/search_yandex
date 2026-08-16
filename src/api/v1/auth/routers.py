from fastapi import APIRouter, HTTPException, status, Response
from dishka.integrations.fastapi import FromDishka,DishkaRoute

from src.api.v1.auth.schema import UserRegister, UserLogin, TokenResponse, UserMeResponse
from src.application.use_cases.login_user import LoginUserUseCase
from src.application.use_cases.registre_user import RegisterUserUseCase
from src.config.settings import settings

router = APIRouter(prefix=settings.api.v1.api_v1 + "/auth", tags=["Auth"], route_class=DishkaRoute)

@router.post("/sign_up", response_model=UserMeResponse, status_code=status.HTTP_201_CREATED, summary="Регистрация администратора")
async def register(
    payload: UserRegister,
    response: Response,
    use_case: FromDishka[RegisterUserUseCase],
):
    user, token = await use_case.execute(
        username=payload.username,
        raw_password=payload.password,
    )

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=not settings.IS_LOCAL,
        max_age=settings.jwt.access_token_expire_minutes * 60,
    )

    return user


@router.post("/login", response_model=TokenResponse, summary="Вход для администратора")
async def login(
    payload: UserLogin,
    response: Response,
    use_case: FromDishka[LoginUserUseCase],
):
    user, token = await use_case.execute(
        username=payload.username,
        raw_password=payload.password,
    )

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=not settings.IS_LOCAL,
        max_age=settings.jwt.access_token_expire_minutes * 60,
    )

    return TokenResponse(access_token=token)



@router.post("/logout", summary="Выход из системы")
async def logout(response: Response):
    response.delete_cookie(key="access_token", samesite="lax")
    return {"message": "Успешный выход"}