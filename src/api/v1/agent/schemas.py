from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, AliasGenerator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class BaseDTO(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        alias_generator=AliasGenerator(
            validation_alias=to_camel,
            serialization_alias=to_camel,
        ),
    )


class AgentChatMessage(BaseDTO):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class AgentChatRequest(BaseDTO):
    chat_id: uuid.UUID | None = Field(default=None, description="UUID сессии диалога в БД")
    messages: list[AgentChatMessage] = Field(
        ...,
        min_length=1,
        description="История диалога; последнее сообщение обычно от user",
    )



class AgentChatListItemDTO(BaseDTO):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime

class AgentChatDetailDTO(BaseDTO):
    id: uuid.UUID
    title: str
    messages: list[dict[str, Any]] = []
    created_at: datetime
    updated_at: datetime