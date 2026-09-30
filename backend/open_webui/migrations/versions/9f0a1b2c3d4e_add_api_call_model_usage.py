"""Store usage from asynchronous model calls.

Revision ID: 9f0a1b2c3d4e
Revises: 8e9f0a1b2c3d
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '9f0a1b2c3d4e'
down_revision: Union[str, None] = '8e9f0a1b2c3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if 'api_call_model_usage' not in sa.inspect(bind).get_table_names():
        op.create_table(
            'api_call_model_usage',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('api_call_id', sa.Text(), nullable=False),
            sa.Column('model_id', sa.Text(), nullable=True),
            sa.Column('user_id', sa.Text(), nullable=True),
            sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
        )
    indexes = {index['name'] for index in sa.inspect(bind).get_indexes('api_call_model_usage')}
    for column in ('api_call_id', 'model_id', 'user_id', 'created_at'):
        name = f'ix_api_call_model_usage_{column}'
        if name not in indexes:
            op.create_index(name, 'api_call_model_usage', [column])


def downgrade() -> None:
    bind = op.get_bind()
    if 'api_call_model_usage' in sa.inspect(bind).get_table_names():
        op.drop_table('api_call_model_usage')
