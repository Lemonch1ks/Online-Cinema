"""seed user groups

Revision ID: 5b1c7e9d2a40
Revises: ea86cc9694ae
Create Date: 2026-10-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b1c7e9d2a40'
down_revision: Union[str, Sequence[str], None] = 'ea86cc9694ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GROUPS = ('USER', 'MODERATOR', 'ADMIN')

# Must match the real column type: on PostgreSQL `name` is the native enum type `usergroupenum`,
# and Postgres does not cast VARCHAR to an enum implicitly. sa.table() never emits CREATE TYPE,
# so the type created in ea86cc9694ae is reused.
user_groups = sa.table('user_groups', sa.column('name', sa.Enum(*GROUPS, name='usergroupenum')))


def upgrade() -> None:
    """Insert the default user groups."""
    existing = {row[0] for row in op.get_bind().execute(sa.select(user_groups.c.name))}
    missing = [{'name': name} for name in GROUPS if name not in existing]
    if missing:
        op.bulk_insert(user_groups, missing)


def downgrade() -> None:
    """Remove the default user groups."""
    op.execute(user_groups.delete().where(user_groups.c.name.in_(GROUPS)))
