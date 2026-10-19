from pydantic import BaseModel

class UserSchema(BaseModel):
    id: int
    email: str
    model_config = {"from_attributes": True}

class UserCreationSchema(BaseModel):
    email: str
    password: str
