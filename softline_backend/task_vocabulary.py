from typing import Literal


Capability = Literal[
    "email_protection",
    "file_protection",
    "endpoint_protection",
    "data_loss_prevention",
    "backup",
    "network_protection",
]
CAPABILITY_LABELS: dict[Capability, str] = {
    "email_protection": "защита почты",
    "file_protection": "защита файлов",
    "endpoint_protection": "защита конечных устройств",
    "data_loss_prevention": "предотвращение утечек данных",
    "backup": "резервное копирование",
    "network_protection": "защита сети",
}
