"""Criar tabela categorias_despesa

Revision ID: 1b11bd61c12b
Revises: 4ef1848d4e49
Create Date: 2025-06-11 15:30:14.382610

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1b11bd61c12b'
down_revision = '4ef1848d4e49'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('categorias_despesa',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=100), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('nome')
    )
    op.create_table('financeiro_usina',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('usina_id', sa.Integer(), nullable=False),
    sa.Column('categoria_id', sa.Integer(), nullable=True),
    sa.Column('data', sa.Date(), nullable=False),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('descricao', sa.String(length=255), nullable=False),
    sa.Column('valor', sa.Float(), nullable=False),
    sa.Column('referencia_mes', sa.Integer(), nullable=True),
    sa.Column('referencia_ano', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['categoria_id'], ['categorias_despesa.id'], ),
    sa.ForeignKeyConstraint(['usina_id'], ['usinas.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('financeiro_usina')
    op.drop_table('categorias_despesa')
    # ### end Alembic commands ###
