"""Add API call analytics storage.

Revision ID: f3a2b1c0d9e8
Revises: d4c1a8e37b62
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from open_webui.migrations.util import get_existing_tables

revision: str = 'f3a2b1c0d9e8'
down_revision: Union[str, None] = 'd4c1a8e37b62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'api_call' not in set(get_existing_tables()):
        op.create_table(
            'api_call',
            sa.Column('id', sa.Text(), nullable=False),
            sa.Column('method', sa.Text(), nullable=False),
            sa.Column('path', sa.Text(), nullable=False),
            sa.Column('status_code', sa.Integer(), nullable=False),
            sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_api_call_method', 'api_call', ['method'])
        op.create_index('ix_api_call_path', 'api_call', ['path'])
        op.create_index('ix_api_call_created_at', 'api_call', ['created_at'])


def downgrade() -> None:
    if 'api_call' in set(get_existing_tables()):
        op.drop_index('ix_api_call_created_at', table_name='api_call')
        op.drop_index('ix_api_call_path', table_name='api_call')
        op.drop_index('ix_api_call_method', table_name='api_call')
        op.drop_table('api_call')
