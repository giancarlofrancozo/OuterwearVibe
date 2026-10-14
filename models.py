from sqlalchemy import Column, Integer, String
from database import Base


class Cliente(Base):
    __tablename__ = "clientes"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    senha_hash = Column(String, nullable=False)
    telefone = Column(String)
    endereco = Column(String)


from sqlalchemy import Float, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship

class Produto(Base):
    __tablename__ = "produtos"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, index=True)
    descricao = Column(String)
    preco = Column(Float, nullable=False)
    imagem_url = Column(String)
    estoque = Column(Integer, nullable=False, default=0)
    categoria = Column(String, index=True)

    imagens = relationship("ImagemProduto", back_populates="produto", cascade="all, delete-orphan", order_by="ImagemProduto.posicao", lazy="selectin")
    tamanhos = relationship("TamanhoProduto", back_populates="produto", cascade="all, delete-orphan", lazy="selectin")


from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

class Pedido(Base):
    __tablename__ = "pedidos"
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False, index=True)
    data = Column(DateTime, server_default=func.now(), nullable=False)
    status = Column(String, nullable=False, default="aguardando pagamento")
    codigo_rastreamento = Column(String, nullable=True)
    total = Column(Float, nullable=False)
    cep = Column(String, nullable=False)
    rua = Column(String, nullable=False)
    numero = Column(String, nullable=False)
    complemento = Column(String, nullable=True)
    bairro = Column(String, nullable=False)
    cidade = Column(String, nullable=False)
    estado = Column(String, nullable=False)

    cliente = relationship("Cliente", backref="pedidos")
    itens = relationship("ItemPedido", back_populates="pedido")

class ItemPedido(Base):
    __tablename__ = "itens_pedido"
    id = Column(Integer, primary_key=True, index=True)
    pedido_id = Column(Integer, ForeignKey("pedidos.id"), nullable=False, index=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False, index=True)
    quantidade = Column(Integer, nullable=False, default=1)
    preco_unitario = Column(Float, nullable=False)
    tamanho = Column(String, nullable=True)

    pedido = relationship("Pedido", back_populates="itens")
    produto = relationship("Produto")


class ImagemProduto(Base):
    __tablename__ = "imagens_produto"
    id = Column(Integer, primary_key=True, index=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False, index=True)
    posicao = Column(Integer, nullable=False, default=0)
    url = Column(String, nullable=False)

    produto = relationship("Produto", back_populates="imagens")


class TamanhoProduto(Base):
    __tablename__ = "tamanhos_produto"
    id = Column(Integer, primary_key=True, index=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False, index=True)
    nome = Column(String, nullable=False)

    produto = relationship("Produto", back_populates="tamanhos")

