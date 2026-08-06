from pydantic import BaseModel, ConfigDict, AliasGenerator
from pydantic.alias_generators import to_camel



common_config = ConfigDict(
    from_attributes=True,
    populate_by_name=True,
    alias_generator=AliasGenerator(
        validation_alias=to_camel,
        serialization_alias=to_camel,
    ),
)

class TextRequest(BaseModel):
    text: str

    model_config = common_config

class DetectResponse(BaseModel):
    ai_percentage: int
    human_percentage: int
    reason: str

    model_config = common_config

class HumanizeResponse(BaseModel):
    humanized_text: str

    model_config = common_config