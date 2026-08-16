from typing import Optional
from sqlalchemy import select
from src.infrastructure.database.base_repository import BaseRepository
from src.infrastructure.database.models.users import User

class UserRepository(BaseRepository[User]):
    def __init__(self, session):
        super().__init__(model=User, session=session)

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username.strip())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

