from dataclasses import dataclass

from src.application.dto import MessagePayloadDto
from src.core.enums import Role


@dataclass(slots=True)
class NotificationTaskDto:
    payload: MessagePayloadDto
    roles: list[Role]
