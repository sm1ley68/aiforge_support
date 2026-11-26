"""Manually checked capability evidence for the initial Softline demo scenario."""

from dataclasses import dataclass, replace

from .contracts import Source


@dataclass(frozen=True)
class VerifiedPackage:
    sku: str
    min_nodes: int
    max_nodes: int
    term_months: int


PACKAGES = (
    VerifiedPackage("KL4869RAQFS", 50, 99, 12),
    VerifiedPackage("KL4869RAQDS", 50, 99, 24),
)

PACKAGE_SOURCES = (
    Source(
        "softline-kts-components", "2026-11-26", "Softline — Kaspersky Total Security для бизнеса",
        "В базовую лицензию входят компоненты защиты Microsoft Exchange и Kaspersky Endpoint Security для Windows. "
        "Диапазон от 50 до 99 узлов указан для артикулов KL4869RAQFS на 12 месяцев и KL4869RAQDS на 24 месяца.",
        "https://store.softline.ru/kaspersky/kaspersky-total-security-dlya-biznesa/",
    ),
    Source(
        "kaspersky-file-servers", "2026-11-26", "Kaspersky — защита файловых серверов",
        "Kaspersky Endpoint Security для Windows поддерживает защиту файловых серверов Windows. "
        "Точные версии и требования нужно сверять с документацией к устанавливаемым компонентам.",
        "https://support.kaspersky.com/KSC/13/ru-RU/172903.htm",
    ),
)

RUSSIAN_SOURCE = Source(
    "kaspersky-ru-software-registry", "2026-11-26", "Kaspersky — перечень в реестре российского ПО",
    "Производитель включает Kaspersky Total Security для бизнеса в свой перечень продуктов из реестра российского ПО.",
    "https://www.kaspersky.ru/small-to-medium-business-security/registry?ignoreredirects=true",
)

CATALOG_KNOWLEDGE = (
    replace(
        PACKAGE_SOURCES[0],
        aliases=(
            "Что входит в базовую лицензию Kaspersky Total Security для бизнеса?",
            "Kaspersky Total Security для бизнеса защищает Microsoft Exchange?",
            "Защищает ли Kaspersky Total Security для бизнеса почту Exchange?",
        ),
        reusable=True,
    ),
    Source(
        "softline-electronic-license-delivery", "2026-11-26", "Получение электронной лицензии",
        "Магазин отправляет электронную лицензию на адрес электронной почты, указанный при заказе. "
        "Срок поставки зависит от позиции и указывается на карточке товара.",
        "https://store.softline.ru/delivery_info/",
        aliases=(
            "Как доставляют электронные лицензии?",
            "Как я получу электронную лицензию?",
            "Куда отправляют электронную лицензию?",
            "Где посмотреть срок доставки электронной лицензии?",
        ),
        reusable=True,
    ),
)
