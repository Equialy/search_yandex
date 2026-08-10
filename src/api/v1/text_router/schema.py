from pydantic import BaseModel, ConfigDict, AliasGenerator
from pydantic.alias_generators import to_camel
import uuid
from pydantic import Field
from src.api.v1.competitors.schemas import BaseDTO




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


class WordFrequencyDTO(BaseDTO):
    word: str = Field(description="Слово в начальной форме (лемма)")
    count: int = Field(description="Количество вхождений в текст")
    frequency_percent: float = Field(description="Процент от общего количества слов")


class CalculateNauseaRequest(BaseDTO):
    text: str = Field(..., min_length=5, description="Текст для анализа SEO-метрик")


class CalculateNauseaResponse(BaseDTO):
    total_words: int = Field(description="Общее количество слов")
    unique_words: int = Field(description="Количество уникальных лемм")
    classic_nausea: float = Field(description="Классическая тошнота (корень из макс. частоты)")
    academic_nausea: float = Field(description="Академическая тошнота (%)")
    top_words: list[WordFrequencyDTO] = Field(default_factory=list, description="Топ самых частых слов")