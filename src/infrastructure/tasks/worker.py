
import logging
from dishka import make_async_container
from dishka.integrations.taskiq import setup_dishka

from src.application.ioc.competitors import CompetitorsProvider
from src.application.ioc.gateways import GatewaysProvider
from src.application.ioc.infrastructure import InfrastructureProvider
from src.config.settings import config_logging
from src.infrastructure.tasks.broker import broker

from src.infrastructure.tasks import tasks  # noqa: F401

config_logging()
logger = logging.getLogger(__name__)

container = make_async_container(
    InfrastructureProvider(),
    GatewaysProvider(),
    CompetitorsProvider(),
)

setup_dishka(container=container, broker=broker)