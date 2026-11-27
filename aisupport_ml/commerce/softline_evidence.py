"""Manually checked capability and licensing evidence for Softline recommendations."""

import re
from dataclasses import dataclass, replace

from .catalog import CatalogOffer
from .contracts import Source
from .support_answers import SUPPORT_ANSWERS


MDAEMON_LICENSING = Source(
    "mdaemon-email-server-licensing", "2026-11-27", "MDaemon — варианты покупки Email Server",
    "Производитель предлагает выбор типа операции, срока и числа пользователей.",
    "https://mdaemon.com/products/mdaemon-email-server",
)


@dataclass(frozen=True)
class VerifiedSeatOffer:
    reference: str
    title: str
    edition: str
    platforms: tuple[str, ...]
    max_devices: int | None
    term_months: int | None
    russian_verified: bool
    source: Source


@dataclass(frozen=True)
class DesktopTask:
    name: str
    pattern: re.Pattern[str]
    offers: tuple[VerifiedSeatOffer, ...]


DESKTOP_TASKS = (
    DesktopTask(
        "планирование проектов",
        re.compile(
            r"\b(?:управлени\w*\s+(?:проект\w*|задач\w*)|планировани\w*\s+проект\w*"
            r"|планировать\s+проект\w*|вести\s+проект\w*)\b",
            re.I,
        ),
        (
            VerifiedSeatOffer(
                "EP2-07001", "Microsoft Project Professional 2024", "Professional 2024", ("windows 10", "windows 11"),
                None, None, False,
                Source(
                    "ms-project-2024", "2026-11-26", "Microsoft — возможности и требования Project Professional 2024",
                    "Поддерживает планирование задач, зависимости и временные шкалы. "
                    "Редакция работает на Windows 10 и 11. Бессрочная лицензия рассчитана на один ПК.",
                    "https://www.microsoft.com/en-us/microsoft-365/p/project-professional-2024/cfq7ttc0ph40",
                ),
            ),
        ),
    ),
    DesktopTask(
        "редактирование PDF",
        re.compile(r"\b(?:редактировани\w*\s+pdf|редактировать\s+pdf|pdf[ -]+редактор\w*|редактор\w*\s+pdf)\b", re.I),
        (
            VerifiedSeatOffer(
                "541420", "PDF Commander Бизнес", "Бизнес", ("windows 10", "windows 11"), 3, None, True,
                Source(
                    "pdf-commander-editing", "2026-11-26", "PDF Commander — редактирование текста PDF",
                    "Прямое редактирование текста PDF доступно в версии для Windows. "
                    "Для бессрочной бизнес-лицензии Windows цена за рабочее место меняется от четырёх копий.",
                    "https://pdf-editor.su/compare-master-pdf-editor.php",
                ),
            ),
            VerifiedSeatOffer(
                "541424", "PDF Commander Бизнес", "Бизнес", ("windows 10", "windows 11"), 3, 12, True,
                Source(
                    "pdf-commander-subscription", "2026-11-26", "PDF Commander — годовая бизнес-лицензия",
                    "Годовая подписка для организаций лицензируется по рабочим местам. "
                    "Прямое редактирование текста PDF доступно в версии для Windows.",
                    "https://pdf-editor.su/compare-master-pdf-editor.php",
                ),
            ),
        ),
    ),
)


def desktop_task(text: str) -> DesktopTask | None:
    matches = [task for task in DESKTOP_TASKS if task.pattern.search(text) or task.name.casefold() == text.casefold()]
    return matches[0] if len(matches) == 1 else None


def desktop_evidence(offer: CatalogOffer) -> VerifiedSeatOffer | None:
    return next((record for task in DESKTOP_TASKS for record in task.offers
                 if record.reference in (offer.offer_id, offer.vendor_code)
                 and record.title.casefold() in offer.title.casefold()), None)


@dataclass(frozen=True)
class VerifiedPackage:
    sku: str
    min_nodes: int
    max_nodes: int
    term_months: int


PACKAGES = (
    VerifiedPackage("KL4869RAPFS", 25, 49, 12),
    VerifiedPackage("KL4869RAPDS", 25, 49, 24),
    VerifiedPackage("KL4869RAQFS", 50, 99, 12),
    VerifiedPackage("KL4869RAQDS", 50, 99, 24),
)

@dataclass(frozen=True)
class BackupLicense:
    sku: str
    min_devices: int
    max_devices: int
    scope: str
    vendor: str
    perpetual: bool = False
    russian_verified: bool = False


BACKUP_LICENSES = (
    BackupLicense("HBS", 1, 1, "files", "handy"),
    BackupLicense("HBS2-3", 2, 3, "files", "handy"),
    BackupLicense("HBS4-9", 4, 9, "files", "handy"),
    BackupLicense("HBS10", 10, 999, "files", "handy"),
    BackupLicense("HBP", 1, 1, "disk_image", "handy"),
    BackupLicense("HBP2-3", 2, 3, "disk_image", "handy"),
    BackupLicense("HBP4-9", 4, 9, "disk_image", "handy"),
    BackupLicense("HBP10", 10, 999, "disk_image", "handy"),
    # The feed code for the Windows workstation card is PCSCNL.
    BackupLicense("PCSCNL", 1, 999, "files", "cyber", perpetual=True, russian_verified=True),
)

BACKUP_SOURCES = {
    "handy": (
        Source(
            "handy-backup-desktop-features", "2026-11-26", "Новософт — сравнение редакций Handy Backup",
            "Standard копирует отдельные файлы и папки на локальные и USB-диски. "
            "Professional также создаёт образы диска. Обе редакции поддерживают Windows 10 и 11.",
            "https://www.handybackup.ru/backup-comparisons.shtml",
        ),
        Source(
            "handy-backup-seat-pricing", "2026-11-26", "Softline — лицензии Handy Backup",
            "В этих позициях цена указана за одну лицензию. Для отдельных установок нужна одна лицензия на компьютер. "
            "Артикул Handy Backup меняется в зависимости от количества покупаемых лицензий.",
            "https://store.softline.ru/novosoft/novosoft-handy-backup/",
        ),
    ),
    "cyber": (
        Source(
            "cyber-backup-workstation", "2026-11-26", "Softline — Кибер Бэкап для рабочей станции Windows",
            "Карточка 421471 относится к бессрочной стандартной лицензии рабочей станции для коммерческих организаций. "
            "Производитель российский.",
            "https://store.softline.ru/cyberprotect/pcs16nl-421471/",
        ),
        Source(
            "cyber-backup-files", "2026-11-26", "Киберпротект — руководство Кибер Бэкап 16",
            "Руководство описывает резервное копирование файлов и папок с установленным агентом "
            "и сохранение копий в локальном хранилище. Поддерживаются рабочие станции Windows 10 и 11.",
            "https://docs.cyberprotect.ru/ru-RU/CyberBackup/16/CyberBackup_userguide_ru-RU.pdf",
        ),
    ),
}

PACKAGE_SOURCES = (
    Source(
        "softline-kts-components", "2026-11-26", "Softline — Kaspersky Total Security для бизнеса",
        "В базовую лицензию входят компоненты защиты Microsoft Exchange и Kaspersky Endpoint Security для Windows. "
        "Для 25–49 узлов подходят KL4869RAPFS и KL4869RAPDS, для 50–99 — KL4869RAQFS и KL4869RAQDS. "
        "Суффиксы FS и DS соответствуют срокам 12 и 24 месяца для этих артикулов.",
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
    Source(
        "softline-store-payment", "2026-11-26", "Способы оплаты в Softline Store",
        "Компания или ИП может оплатить заказ банковским переводом. "
        "В магазине также доступна оплата картой. Для физлиц есть СБП, цифровой рубль и SberPay.",
        "https://store.softline.ru/delivery_info/",
        aliases=(
            "Как оплатить заказ", "Какие способы оплаты есть", "Чем можно оплатить покупку",
            "Можно оплатить картой", "Можно оплатить по безналу", "Можно оплатить банковским переводом",
            "Как юрлицу оплатить заказ",
        ),
        reusable=True,
    ),
    Source(
        "softline-lk-invoices", "2026-11-26", "Счёт на оплату в личном кабинете Softline",
        "Войдите в личный кабинет «Софтлайн Цифровой Актив» и откройте раздел «Счета и платежи». "
        "Найдите заказ, например по номеру, и скачайте документ для оплаты. "
        "Список доступных заказов зависит от вашей учётной записи и её прав.",
        "https://docs.softline.com/ru-ru/lk/invoices",
        aliases=(
            "Где скачать счет", "Как скачать счет на оплату", "Где счет за заказ",
            "Где найти счет в личном кабинете", "Не вижу счет в личном кабинете",
            "Можно скачать счет из личного кабинета", "Как получить счет по существующему заказу",
        ),
        reusable=True,
    ),
    *SUPPORT_ANSWERS.values(),
    Source(
        "softline-lk-closing-documents", "2026-11-26", "Закрывающие документы по заказу",
        "Для заказа, самостоятельно оформленного в Store, найдите его в разделе «Счета и платежи» "
        "личного кабинета и скачайте закрывающие документы из карточки заказа. "
        "Если заказ оформлял менеджер, документы предоставляет он.",
        "https://docs.softline.com/ru-ru/lk/closing-documents",
        aliases=(
            "Где скачать закрывающие документы", "Как получить закрывающие документы для бухгалтерии",
            "Где взять закрывающие документы", "Где скачать УПД",
            "Как скачать УПД по заказу", "Где найти акт по заказу",
        ),
        reusable=True,
    ),
)
