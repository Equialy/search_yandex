
import uuid
from pydantic import AliasChoices, AliasGenerator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

common_config = ConfigDict(
    from_attributes=True,
    populate_by_name=True,
    alias_generator=AliasGenerator(
        validation_alias=to_camel,
        serialization_alias=to_camel,
    ),
)


class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)

    model_config = common_config


class UserLogin(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)

    model_config = common_config


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

    model_config = common_config


class UserMeResponse(BaseModel):
    id: uuid.UUID
    username: str
    role: str
    is_active: bool

    model_config = common_config