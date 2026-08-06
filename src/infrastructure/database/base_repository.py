from typing import TypeVar, Generic, Type, Optional, Sequence, Any, Union
from sqlalchemy import select
from sqlalchemy.ext.asyncio import  AsyncSession
from sqlalchemy.orm import class_mapper
from uuid import UUID

from src.infrastructure.database.engine import Base
import sqlalchemy as sa

T = TypeVar("T", bound=Base)

class BaseRepository(Generic[T]):
    def __init__(self, model: Type[T], session: AsyncSession):
        self.model = model
        self.session = session

    @staticmethod
    def _model_field_keys(model: Type[T]) -> set[str]:
        """Имена атрибутов ORM (agent_key), не колонок БД (key)."""
        return {attr.key for attr in class_mapper(model).column_attrs}

    async def get_by_id(self, obj_id: Union[int, UUID, str]) -> Optional[T]:
        return await self.session.get(self.model, obj_id)

    async def get_one_by(self, **kwargs: Any) -> Optional[T]:
        query = select(self.model).filter_by(**kwargs)
        result = await self.session.execute(query)
        return result.scalars().first()

    async def get_list_by(self, **kwargs: Any) -> Sequence[T]:
        query = select(self.model).filter_by(**kwargs)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_by_users_id(self, obj_id: str) -> Optional[T]:
        return await self.session.get(self.model, obj_id)

    async def get_all(self, skip: int = 0, limit: int = 100) -> Sequence[T]:
        query = select(self.model).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def add(self, data: Union[T, dict]) -> T:
        if isinstance(data, self.model):
            obj = data
        elif isinstance(data, dict):
            field_keys = self._model_field_keys(self.model)
            payload = {k: v for k, v in data.items() if k in field_keys}
            obj = self.model(**payload)
        else:
            raise ValueError(f"Expected dict or {self.model.__name__}, got {type(data)}")

        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def update(self, obj_id: int, data: dict) -> Optional[T]:
        obj = await self.session.get(self.model, obj_id)
        if obj:
            for key, value in data.items():
                setattr(obj, key, value)
            await self.session.flush()
        return obj

    async def update_by_filters(self, filters: dict, data: dict) -> bool:
        if not filters:
            raise ValueError("Filters cannot be empty for update operation")
        stmt = (
            sa.update(self.model)
            .filter_by(**filters)
            .values(**data)
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def delete(self, **kwargs) -> bool:
        stmt = sa.delete(self.model).filter_by(**kwargs)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0