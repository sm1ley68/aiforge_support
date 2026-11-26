"""Manually checked capability and licensing evidence for Softline recommendations."""

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
