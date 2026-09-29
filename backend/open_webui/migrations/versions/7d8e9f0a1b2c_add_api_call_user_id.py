"""Attribute API calls to authenticated users.

Revision ID: 7d8e9f0a1b2c
Revises: f3a2b1c0d9e8
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '7d8e9f0a1b2c'
down_revision: Union[str, None] = 'f3a2b1c0d9e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column['name'] for column in sa.inspect(bind).get_columns('api_call')}
    if 'user_id' not in columns:
        op.add_column('api_call', sa.Column('user_id', sa.Text(), nullable=True))
    indexes = {index['name'] for index in sa.inspect(bind).get_indexes('api_call')}
    if 'ix_api_call_user_id' not in indexes:
        op.create_index('ix_api_call_user_id', 'api_call', ['user_id'])


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index['name'] for index in sa.inspect(bind).get_indexes('api_call')}
    if 'ix_api_call_user_id' in indexes:
        op.drop_index('ix_api_call_user_id', table_name='api_call')
    columns = {column['name'] for column in sa.inspect(bind).get_columns('api_call')}
    if 'user_id' in columns:
        op.drop_column('api_call', 'user_id')
