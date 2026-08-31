
"""
Определение брокера Taskiq.

ВАЖНО: этот модуль НЕ должен импортировать ничего из application-слоя
(ioc, use cases, сервисы). Иначе возникает циклический импорт:
broker -> ioc -> use_case -> tasks -> broker.

Здесь только инфраструктура очереди: RabbitMQ (транспорт) + Redis (результаты).
"""
from taskiq.brokers.shared_broker import async_shared_broker
from taskiq_aio_pika import AioPikaBroker
from taskiq_redis import RedisAsyncResultBackend

from src.config.settings import settings

result_backend = RedisAsyncResultBackend(
    redis_url=settings.redis.backend_url,
    result_ex_time=60 * 60 * 24,
)

broker = AioPikaBroker(
    url=settings.rabbitmq.url,
    qos=1,
).with_result_backend(result_backend)

async_shared_broker.default_broker(broker)