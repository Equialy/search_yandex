from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncEngine, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from src.config.database import DatabaseConfig




POSTGRES_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=POSTGRES_NAMING_CONVENTION)




def new_engine(
    db_config: DatabaseConfig,
) -> AsyncEngine:
    async_engine = create_async_engine(
        url=db_config.async_url,
        pool_size=db_config.sqla.pool_size,
        max_overflow=db_config.sqla.max_overflow,
        connect_args=db_config.sqla.connect_args,
    )
    return async_engine


def new_session_maker(
    async_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=async_engine,
        autoflush=False,
        expire_on_commit=False,
    )