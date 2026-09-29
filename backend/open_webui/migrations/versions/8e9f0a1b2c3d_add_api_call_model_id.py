"""Attribute API calls to models.

Revision ID: 8e9f0a1b2c3d
Revises: 7d8e9f0a1b2c
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '8e9f0a1b2c3d'
down_revision: Union[str, None] = '7d8e9f0a1b2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column['name'] for column in sa.inspect(bind).get_columns('api_call')}
    if 'model_id' not in columns:
        op.add_column('api_call', sa.Column('model_id', sa.Text(), nullable=True))
    indexes = {index['name'] for index in sa.inspect(bind).get_indexes('api_call')}
    if 'ix_api_call_model_id' not in indexes:
        op.create_index('ix_api_call_model_id', 'api_call', ['model_id'])


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index['name'] for index in sa.inspect(bind).get_indexes('api_call')}
    if 'ix_api_call_model_id' in indexes:
        op.drop_index('ix_api_call_model_id', table_name='api_call')
    columns = {column['name'] for column in sa.inspect(bind).get_columns('api_call')}
    if 'model_id' in columns:
        op.drop_column('api_call', 'model_id')
