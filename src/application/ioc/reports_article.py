from dishka import Provider, provide, Scope

from infrastructure.gateways.reports_article import ReportsArticleGateway


class ReportsArticleProvider(Provider):
    reports_gateway = provide(
        ReportsArticleGateway,
        scope=Scope.APP,
    )
