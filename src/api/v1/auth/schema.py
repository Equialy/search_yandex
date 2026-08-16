from pydantic import BaseModel, EmailStr, ConfigDict, AliasGenerator
from uuid import UUID
from typing import Optional

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
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserMeResponse(BaseModel):
    id: UUID
    username: str
    role: str
    tokens_balance: int
    balance: float

    model_config = common_config