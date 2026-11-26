from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .contracts import MessageView
from .task_vocabulary import CAPABILITY_LABELS, Capability


SearchWord = Annotated[str, StringConstraints(
    min_length=2,
    max_length=40,
    pattern=r"^[а-яА-ЯёЁa-zA-Z0-9]+$",
)]


class TaskExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    intent: Literal["task", "clarify", "not_task"]
    terms: list[SearchWord] = Field(max_length=8)
    capabilities: list[Capability] = Field(max_length=len(CAPABILITY_LABELS))
    user_limit: Annotated[int, Field(ge=1, le=9_999_999)] | None
    deployment: Literal["локально", "облако"] | None
    budget_rubles: Annotated[int, Field(ge=0, le=999_999_999_999)] | None
    origin: Literal["Россия"] | None
    missing: Literal["purpose", "constraints"] | None

    @model_validator(mode="after")
    def check_intent(self):
        if self.intent == "task" and (self.missing or not (self.terms or self.capabilities)):
            raise ValueError("Actionable task requires terms or capabilities and no unresolved constraints")
        if self.intent == "clarify" and self.missing is None:
            raise ValueError("Clarification requires a reason")
        return self


TaskExtractor = Callable[[str, list[MessageView]], TaskExtraction | None]
