from datetime import datetime, timedelta, timezone
import os
import jwt
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from database import engine, Base, SessionLocal
from pagamentos import criar_link_pagamento, consultar_pagamento, consultar_pedido_mp
import models
import schemas

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = os.environ["SECRET_KEY"]
ADMIN_KEY = os.environ["ADMIN_KEY"]
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60

bearer = HTTPBearer()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def criar_token(cliente_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(cliente_id),
        "exp": expire
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def cliente_atual(
    credenciais: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
):
    token = credenciais.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")

    cliente = db.query(models.Cliente).filter(models.Cliente.id == int(payload["sub"])).first()
    if not cliente:
        raise HTTPException(status_code=401, detail="Cliente não encontrado")
    return cliente


def verifica_admin(x_admin_key: str = Header(...)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Acesso negado")


@app.get("/")
def inicio():
    return {"message": "Loja no ar"}

@app.get("/admin", include_in_schema=False)
def painel_admin():
    return FileResponse(os.path.join("static", "admin.html"))

@app.get("/vitrine", include_in_schema=False)
def vitrine():
    return FileResponse(os.path.join("static", "index.html"))


@app.post("/clientes", response_model=schemas.ClienteResposta, status_code=201)
def criar_cliente(dados: schemas.ClienteCriar, db: Session = Depends(get_db)):
    cliente_existente = db.query(models.Cliente).filter(models.Cliente.email == dados.email).first()
    if cliente_existente:
        raise HTTPException(status_code=400, detail="Email já cadastrado")

    senha_hash = pwd_context.hash(dados.senha)

    novo_cliente = models.Cliente(
        nome=dados.nome,
        email=dados.email,
        senha_hash=senha_hash,
        telefone=dados.telefone,
        endereco=dados.endereco
    )
    db.add(novo_cliente)
    db.commit()
    db.refresh(novo_cliente)

    return novo_cliente


@app.post("/login", response_model=schemas.Token)
def login(dados: schemas.LoginEntrada, db: Session = Depends(get_db)):
    cliente = db.query(models.Cliente).filter(models.Cliente.email == dados.email).first()
    if not cliente or not pwd_context.verify(dados.senha, cliente.senha_hash):
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")

    return schemas.Token(access_token=criar_token(cliente.id))


@app.get("/produtos", response_model=list[schemas.ProdutoResposta])
def listar_produtos(db: Session = Depends(get_db)):
    return db.query(models.Produto).filter(models.Produto.estoque > 0).all()


@app.post("/produtos", response_model=schemas.ProdutoResposta, status_code=201, dependencies=[Depends(verifica_admin)])
def criar_produto(dados: schemas.ProdutoCriar, db: Session = Depends(get_db)):
    produto = models.Produto(**dados.model_dump())
    db.add(produto)
    db.commit()
    db.refresh(produto)
    return produto


@app.post("/pedidos", response_model=schemas.PedidoResposta, status_code=201)
def criar_pedido(
    dados: schemas.PedidoCriar,
    cliente: models.Cliente = Depends(cliente_atual),
    db: Session = Depends(get_db),
):
    if not dados.itens:
        raise HTTPException(status_code=400, detail="O pedido precisa ter pelo menos um item")

    total = 0.0
    itens = []

    for item in dados.itens:
        if item.quantidade <= 0:
            raise HTTPException(status_code=400, detail="A quantidade deve ser maior que zero")

        produto = db.query(models.Produto).filter(models.Produto.id == item.produto_id).first()
        if not produto:
            raise HTTPException(status_code=404, detail=f"Produto {item.produto_id} não encontrado")
        if produto.estoque < item.quantidade:
            raise HTTPException(status_code=400, detail=f"Estoque insuficiente para {produto.nome}")

        produto.estoque -= item.quantidade
        total += produto.preco * item.quantidade
        itens.append(
            models.ItemPedido(
                produto_id=produto.id,
                quantidade=item.quantidade,
                preco_unitario=produto.preco,
            )
        )

    pedido = models.Pedido(
        cliente_id=cliente.id,
        total=total,
        itens=itens,
        cep=dados.endereco.cep,
        rua=dados.endereco.rua,
        numero=dados.endereco.numero,
        complemento=dados.endereco.complemento,
        bairro=dados.endereco.bairro,
        cidade=dados.endereco.cidade,
        estado=dados.endereco.estado,
    )
    db.add(pedido)
    db.commit()
    db.refresh(pedido)

    return pedido


@app.get("/meus-pedidos", response_model=list[schemas.PedidoResposta])
def meus_pedidos(
    cliente: models.Cliente = Depends(cliente_atual),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.Pedido)
        .filter(models.Pedido.cliente_id == cliente.id)
        .order_by(models.Pedido.data.desc())
        .all()
    )


@app.patch("/admin/pedidos/{pedido_id}", response_model=schemas.PedidoResposta, dependencies=[Depends(verifica_admin)])
def atualizar_pedido(
    pedido_id: int,
    dados: schemas.PedidoAtualizar,
    db: Session = Depends(get_db),
):
    pedido = db.query(models.Pedido).filter(models.Pedido.id == pedido_id).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    if dados.status is not None:
        pedido.status = dados.status
    if dados.codigo_rastreamento is not None:
        pedido.codigo_rastreamento = dados.codigo_rastreamento

    db.commit()
    db.refresh(pedido)
    return pedido


@app.post("/pedidos/{pedido_id}/pagar")
def pagar_pedido(
    pedido_id: int,
    cliente: models.Cliente = Depends(cliente_atual),
    db: Session = Depends(get_db),
):
    pedido = (
        db.query(models.Pedido)
        .filter(models.Pedido.id == pedido_id, models.Pedido.cliente_id == cliente.id)
        .first()
    )
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    itens = [
        {
            "titulo": item.produto.nome,
            "quantidade": item.quantidade,
            "preco_unitario": item.preco_unitario,
        }
        for item in pedido.itens
    ]

    link = criar_link_pagamento(pedido.id, itens)
    return {"pedido_id": pedido.id, "link_pagamento": link}


@app.post("/webhook/mercadopago")
async def webhook_mercadopago(request: Request, db: Session = Depends(get_db)):
    params = request.query_params
    tipo = params.get("topic") or params.get("type")
    recurso_id = params.get("id") or params.get("data.id")

    if recurso_id is None:
        try:
            corpo = await request.json()
        except Exception:
            corpo = {}
        tipo = tipo or corpo.get("topic") or corpo.get("type")
        recurso_id = corpo.get("data", {}).get("id") or corpo.get("id")

    if not recurso_id:
        return {"ok": True}

    if tipo == "merchant_order":
        ordem = consultar_pedido_mp(str(recurso_id))
        pago = any(p.get("status") == "approved" for p in ordem.get("payments", []))
        pedido_ref = ordem.get("external_reference")
    elif tipo == "payment":
        pagamento = consultar_pagamento(str(recurso_id))
        pago = pagamento.get("status") == "approved"
        pedido_ref = pagamento.get("external_reference")
    else:
        return {"ok": True}

    if pago and pedido_ref:
        pedido = db.query(models.Pedido).filter(models.Pedido.id == int(pedido_ref)).first()
        if pedido and pedido.status != "pago":
            pedido.status = "pago"
            db.commit()

    return {"ok": True}