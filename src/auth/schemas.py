from datetime import date

from fastapi import UploadFile
from pydantic import BaseModel, EmailStr, Field, field_validator, AliasPath

from src.auth.models import GenderEnum, UserGroupEnum
from src.auth.validators import validate_birth_date, validate_name, validate_password


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


class AdminChangesUserSchema(BaseModel):
    id: int
    email: EmailStr
    group_rank: UserGroupEnum = Field(validation_alias=AliasPath("group", "name"))
    is_active: bool

    model_config = {"from_attributes": True}


class ProfileFormSchema(BaseModel):
    """Profile fields and the avatar file, sent as multipart/form-data.

    The file is part of the model on purpose: FastAPI cannot combine a Form() model with a separate File()
    parameter (the model would then be expected as one form field named after the parameter).
    For PATCH only the fields that were sent are changed (model_fields_set).
    """
    first_name: str | None = Field(None, max_length=50)
    last_name: str | None = Field(None, max_length=50)
    gender: GenderEnum | None = None
    date_of_birth: date | None = None
    info: str | None = Field(None, max_length=1000)
    avatar: UploadFile | None = Field(None, description="JPEG or PNG, up to 1 MB")

    @field_validator("first_name", "last_name")
    @classmethod
    def check_name(cls, value: str | None) -> str | None:
        return validate_name(value) if value is not None else None

    @field_validator("date_of_birth")
    @classmethod
    def check_birth_date(cls, value: date | None) -> date | None:
        return validate_birth_date(value) if value is not None else None


class ProfileSchema(BaseModel):
    id: int
    user_id: int
    first_name: str | None
    last_name: str | None
    gender: GenderEnum | None
    date_of_birth: date | None
    info: str | None
    avatar_url: str | None
