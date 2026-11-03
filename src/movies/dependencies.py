from fastapi import Depends

from src.auth.dependencies import require_role
from src.auth.models import UserGroupEnum

need_moderator = Depends(require_role(UserGroupEnum.MODERATOR))
