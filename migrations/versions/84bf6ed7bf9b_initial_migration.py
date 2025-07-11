"""Initial migration

Revision ID: 84bf6ed7bf9b
Revises: 
Create Date: 2025-06-04 10:54:40.290735

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '84bf6ed7bf9b'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('analysis_result',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('timeframe', sa.String(length=10), nullable=False),
    sa.Column('start_date', sa.DateTime(), nullable=False),
    sa.Column('end_date', sa.DateTime(), nullable=False),
    sa.Column('success_rate', sa.Float(), nullable=False),
    sa.Column('optimal_leverage', sa.Float(), nullable=False),
    sa.Column('optimal_stop_loss', sa.Float(), nullable=False),
    sa.Column('optimal_take_profit', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=80), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=128), nullable=True),
    sa.Column('api_key', sa.String(length=128), nullable=True),
    sa.Column('api_secret', sa.String(length=128), nullable=True),
    sa.Column('telegram_chat_id', sa.String(length=50), nullable=True),
    sa.Column('balance', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('username')
    )
    op.create_table('trading_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('timeframe', sa.String(length=10), nullable=False),
    sa.Column('leverage', sa.Float(), nullable=False),
    sa.Column('stop_loss', sa.Float(), nullable=False),
    sa.Column('take_profit', sa.Float(), nullable=False),
    sa.Column('binance_active', sa.Boolean(), nullable=True),
    sa.Column('telegram_active', sa.Boolean(), nullable=True),
    sa.Column('api_key', sa.String(length=128), nullable=True),
    sa.Column('api_secret', sa.String(length=128), nullable=True),
    sa.Column('balance', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('transaction',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=20), nullable=False),
    sa.Column('type', sa.String(length=10), nullable=False),
    sa.Column('price', sa.Float(), nullable=False),
    sa.Column('amount', sa.Float(), nullable=False),
    sa.Column('leverage', sa.Float(), nullable=True),
    sa.Column('stop_loss', sa.Float(), nullable=True),
    sa.Column('take_profit', sa.Float(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('transaction')
    op.drop_table('trading_settings')
    op.drop_table('user')
    op.drop_table('analysis_result')
    # ### end Alembic commands ###
