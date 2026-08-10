from __future__ import annotations

from pydantic import AliasChoices, AliasGenerator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class BaseDTO(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=AliasGenerator(
            validation_alias=lambda field_name: AliasChoices(field_name, to_camel(field_name)),
            serialization_alias=to_camel,
        ),
    )


class AgentChatMessage(BaseDTO):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class AgentChatRequest(BaseDTO):
    messages: list[AgentChatMessage] = Field(
        ...,
        min_length=1,
        description="История диалога; последнее сообщение обычно от user",
    )
