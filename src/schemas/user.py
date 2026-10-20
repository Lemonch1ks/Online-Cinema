from pydantic import BaseModel, EmailStr, field_validator
from src.db.validators import validate_password

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
