from pathlib import Path
from typing import Annotated
from fastapi import Depends
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging
from datetime import datetime, timezone

from src.config.database import DatabaseConfig

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class ApiV1Prefix(BaseModel):
    api_v1: str = "/api/v1"
    auth: str = "/auth"
    users: str = "/users"

class ApiPrefix(BaseModel):
    v1: ApiV1Prefix = ApiV1Prefix()

    @property
    def bearer_token_url(self) -> str:
        parts = (self.prefix, self.v1.prefix, self.v1.auth, "/login")
        path = "".join(parts)
        return path.removeprefix("/")

class KIEConfig(BaseModel):
    API_KEY: str
    callback_url: str
    KIE_BASE_URL: str
    jobs_endpoint: str =  Field(
        default="/api/v1/jobs/createTask",
    )

class Redis(BaseModel):
    HOST: str = Field(
        default="localhost",
        description="localhost при локальном запуске, 'redis' внутри docker-compose",
    )
    PORT: int = 6379

    @property
    def backend_url(self) -> str:
        return f"redis://{self.HOST}:{self.PORT}/0"

class RabbitMQ(BaseModel):
    USER: str
    PASSWORD: str
    HOST: str = Field(
        default="localhost",
        description="localhost при локальном запуске, 'rabbitmq' внутри docker-compose",
    )
    PORT: int = 5672

    @property
    def url(self) -> str:
        return f"amqp://{self.USER}:{self.PASSWORD}@{self.HOST}:{self.PORT}/"


class ReportsArticle(BaseModel):
    SECRET_KEY: str

class JwtSettings(BaseModel):
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

class CloudflareR2Config(BaseModel):
    account_id: str = Field(description="Cloudflare Account ID")
    access_key_id: str = Field(description="Access Key ID для R2")
    secret_access_key: str = Field(description="Secret Access Key для R2")
    bucket_name: str = Field(description="Имя бакета в R2 (например, music-tech-media)")
    cdn_url: str = Field(
        default="https://media.playprofi.com",
        description="Публичный CDN URL или r2.dev адрес"
    )

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"

class Proxy(BaseModel):
    HTTP_PROXY: str

class OpenAI(BaseModel):
    API_KEY: str
    MODEL: str
    VISION_MODEL: str = Field(
        default="gpt-4o-mini",
        description="Модель для запросов с изображением (gpt-4o-mini поддерживает vision)",
    )


class Settings(BaseSettings):
    """
    Настройки модели.
    """
    IS_LOCAL: bool
    debug: bool
    base_url: str
    api: ApiPrefix = ApiPrefix()
    redis: Redis
    app_host: str
    app_port: int
    cors_origins: list[str]
    test: int
    rabbitmq: RabbitMQ
    db: DatabaseConfig
    jwt: JwtSettings
    kie: KIEConfig
    r2: CloudflareR2Config
    YANDEX_API_KEY: str
    YANDEX_FOLDER_ID: str
    OPENAI: OpenAI
    proxy: Proxy
    reports: ReportsArticle
    # sqla: SQLAlchemy

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

def get_settings():
    return Settings()

def config_logging(level=logging.INFO):
    logs_dir = BASE_DIR / "logs"
    logs_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=level,
        datefmt="%Y-%m-%d %H:%M:%S",
        format="[%(asctime)s.%(msecs)03d] %(module)7s:%(lineno)-3d %(levelname)-7s - %(message)s",
        handlers=[
            logging.FileHandler(BASE_DIR / "logs/logs.log"),
            logging.StreamHandler(),
        ],
    )


settings = get_settings()