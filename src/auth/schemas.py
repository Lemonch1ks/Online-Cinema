from pydantic import BaseModel, EmailStr, Field, field_validator, AliasPath

from src.auth.models import UserGroupEnum
from src.auth.validators import validate_password


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class TokenData(BaseModel):
    email: str


class TokenVerifySchema(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserSchema(BaseModel):
    id: int
    email: EmailStr
    model_config = {"from_attributes": True}


class EmailRequestSchema(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        return value.lower()


class UserCreationSchema(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        return value.lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        return validate_password(value)


class UserChangePasswordSchema(BaseModel):
    new_password: str
    old_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value):
        return validate_password(value)


class UserNewPasswordSchema(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value):
        return validate_password(value)


class AdminChangeGroupSchema(BaseModel):
    new_group_rank: UserGroupEnum


class UserWithGroupSchema(UserSchema):
    group_rank: UserGroupEnum = Field(validation_alias=AliasPath("group", "name"))
