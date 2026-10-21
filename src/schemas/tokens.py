from pydantic import BaseModel, Field


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class TokenData(BaseModel):
    email: str


class TokenVerifySchema(BaseModel):
    refresh_token: str = Field(min_length=1)
