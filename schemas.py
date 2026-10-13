import re
from datetime import datetime
from pydantic import BaseModel, field_validator


class ClienteCriar(BaseModel):
    nome: str
    email: str
    senha: str
    telefone: str | None = None
    endereco: str | None = None

    @field_validator("senha")
    @classmethod
    def valida_senha(cls, valor):
        if len(valor) < 8:
            raise ValueError("A senha deve ter pelo menos 8 caracteres")
        return valor

    @field_validator("telefone")
    @classmethod
    def valida_telefone(cls, valor):
        if valor is None:
            return valor
        if not re.fullmatch(r"\+?\d{10,13}", valor):
            raise ValueError("Telefone deve conter apenas dígitos (10 a 13)")
        return valor


class ClienteResposta(BaseModel):
    id: int
    nome: str
    email: str
    telefone: str | None = None
    endereco: str | None = None

    model_config = {"from_attributes": True}

class LoginEntrada(BaseModel):
    email: str
    senha: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProdutoCriar(BaseModel):
    nome: str
    descricao: str | None = None
    preco: float
    imagem_url: str | None = None
    estoque: int = 0
    categoria: str | None = None

class EnderecoEntrega(BaseModel):
    cep: str
    rua: str
    numero: str
    complemento: str | None = None
    bairro: str
    cidade: str
    estado: str

    @field_validator("cep")
    @classmethod
    def valida_cep(cls, valor):
        if not re.fullmatch(r"\d{5}-?\d{3}", valor):
            raise ValueError("CEP deve estar no formato 00000-000")
        return valor

    @field_validator("estado")
    @classmethod
    def valida_estado(cls, valor):
        if len(valor) != 2:
            raise ValueError("Estado deve ser a sigla com 2 letras, como SP")
        return valor.upper()

class ProdutoResposta(ProdutoCriar):
    id: int

    model_config = {"from_attributes": True}

class ItemPedidoCriar(BaseModel):
    produto_id: int
    quantidade: int = 1


class PedidoCriar(BaseModel):
    itens: list[ItemPedidoCriar]
    endereco: EnderecoEntrega


class ItemPedidoResposta(BaseModel):
    produto_id: int
    quantidade: int
    preco_unitario: float

    model_config = {"from_attributes": True}


class PedidoResposta(BaseModel):
    id: int
    status: str
    codigo_rastreamento: str | None = None
    total: float
    data: datetime
    cep: str
    rua: str
    numero: str
    complemento: str | None = None
    bairro: str
    cidade: str
    estado: str
    itens: list[ItemPedidoResposta]

    model_config = {"from_attributes": True}

class PedidoAtualizar(BaseModel):
    status: str | None = None
    codigo_rastreamento: str | None = None