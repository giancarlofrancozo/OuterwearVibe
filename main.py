from datetime import datetime, timedelta, timezone
import os
import jwt
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload
from database import engine, Base, SessionLocal
from pagamentos import criar_link_pagamento, consultar_pagamento, consultar_pedido_mp
import models
import schemas


MINUTOS_PARA_PAGAR = 30
STATUS_PENDENTE = ["aguardando pagamento", "Pagamento Pendente"]


def _parse_imagens(dados_imagens):
    """Converte a lista enviada pelo cliente em objetos ImagemProduto."""
    imagens = []
    for i, img in enumerate(dados_imagens):
        if getattr(img, "url", None):
            imagens.append(models.ImagemProduto(url=img.url, posicao=getattr(img, "posicao", i)))
    return imagens


def _parse_tamanhos(dados_tamanhos):
    """Converte a lista enviada pelo cliente em objetos TamanhoProduto."""
    return [models.TamanhoProduto(nome=t.nome.strip()) for t in dados_tamanhos if getattr(t, "nome", None)]


def _sync_imagens(produto, novas_imagens):
    """Substitui as imagens do produto pela lista informada."""
    for img in list(produto.imagens):
        produto.imagens.remove(img)
    for img in _parse_imagens(novas_imagens):
        produto.imagens.append(img)


def _sync_tamanhos(produto, novos_tamanhos):
    """Substitui os tamanhos do produto pela lista informada."""
    for t in list(produto.tamanhos):
        produto.tamanhos.remove(t)
    for t in _parse_tamanhos(novos_tamanhos):
        produto.tamanhos.append(t)


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


def cancelar_pedidos_vencidos(db: Session):
    """Cancela pedidos sem pagamento após o prazo e devolve o estoque."""
    vencidos = (
        db.query(models.Pedido)
        .filter(
            models.Pedido.status.in_(STATUS_PENDENTE),
            models.Pedido.data < func.now() - timedelta(minutes=MINUTOS_PARA_PAGAR),
        )
        .all()
    )
    for pedido in vencidos:
        for item in pedido.itens:
            item.produto.estoque += item.quantidade
        pedido.status = "cancelado"
    if vencidos:
        db.commit()


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
    cancelar_pedidos_vencidos(db)
    return (
        db.query(models.Produto)
        .options(
            selectinload(models.Produto.imagens),
            selectinload(models.Produto.tamanhos),
        )
        .filter(models.Produto.ativo == True, models.Produto.estoque > 0)
        .all()
    )


@app.get("/admin/produtos", response_model=list[schemas.ProdutoResposta], dependencies=[Depends(verifica_admin)])
def listar_todos_produtos(db: Session = Depends(get_db)):
    return (
        db.query(models.Produto)
        .options(
            selectinload(models.Produto.imagens),
            selectinload(models.Produto.tamanhos),
        )
        .order_by(models.Produto.id)
        .all()
    )


@app.post("/produtos", response_model=schemas.ProdutoResposta, status_code=201, dependencies=[Depends(verifica_admin)])
def criar_produto(dados: schemas.ProdutoCriar, db: Session = Depends(get_db)):
    dump = dados.model_dump(exclude={"imagens", "tamanhos"})
    produto = models.Produto(**dump)
    db.add(produto)
    db.commit()
    db.refresh(produto)

    if dados.imagens:
        _sync_imagens(produto, dados.imagens)
    if dados.tamanhos:
        _sync_tamanhos(produto, dados.tamanhos)

    db.commit()
    db.refresh(produto)
    return produto


@app.patch("/admin/produtos/{produto_id}", response_model=schemas.ProdutoResposta, dependencies=[Depends(verifica_admin)])
def atualizar_produto(
    produto_id: int,
    dados: schemas.ProdutoAtualizar,
    db: Session = Depends(get_db),
):
    produto = (
        db.query(models.Produto)
        .options(
            selectinload(models.Produto.imagens),
            selectinload(models.Produto.tamanhos),
        )
        .filter(models.Produto.id == produto_id)
        .first()
    )
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    if dados.nome is not None:
        produto.nome = dados.nome
    if dados.descricao is not None:
        produto.descricao = dados.descricao
    if dados.preco is not None:
        produto.preco = dados.preco
    if dados.imagem_url is not None:
        produto.imagem_url = dados.imagem_url
    if dados.estoque is not None:
        produto.estoque = dados.estoque
    if dados.categoria is not None:
        produto.categoria = dados.categoria
    if dados.ativo is not None:
        produto.ativo = dados.ativo
    if dados.imagens is not None:
        _sync_imagens(produto, dados.imagens)
    if dados.tamanhos is not None:
        _sync_tamanhos(produto, dados.tamanhos)

    db.commit()
    db.refresh(produto)
    return produto


@app.delete("/admin/produtos/{produto_id}", status_code=204, dependencies=[Depends(verifica_admin)])
def excluir_produto(produto_id: int, db: Session = Depends(get_db)):
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    ja_vendido = db.query(models.ItemPedido).filter(models.ItemPedido.produto_id == produto_id).first()
    if ja_vendido:
        raise HTTPException(
            status_code=409,
            detail="Produto já tem pedidos. Arquive o produto em vez de excluir.",
        )

    db.delete(produto)
    db.commit()
    return None


@app.post("/pedidos", response_model=schemas.PedidoResposta, status_code=201)
def criar_pedido(
    dados: schemas.PedidoCriar,
    cliente: models.Cliente = Depends(cliente_atual),
    db: Session = Depends(get_db),
):
    cancelar_pedidos_vencidos(db)

    if not dados.itens:
        raise HTTPException(status_code=400, detail="O pedido precisa ter pelo menos um item")

    total = 0.0
    itens = []

    for item in dados.itens:
        if item.quantidade <= 0:
            raise HTTPException(status_code=400, detail="A quantidade deve ser maior que zero")

        produto = (
            db.query(models.Produto)
            .options(selectinload(models.Produto.tamanhos))
            .filter(models.Produto.id == item.produto_id)
            .first()
        )
        if not produto or not produto.ativo:
            raise HTTPException(status_code=404, detail=f"Produto {item.produto_id} não encontrado")
        if produto.estoque < item.quantidade:
            raise HTTPException(status_code=400, detail=f"Estoque insuficiente para {produto.nome}")

        tamanho_escolhido = (item.tamanho or "").strip()
        if produto.tamanhos:
            if not tamanho_escolhido:
                raise HTTPException(status_code=400, detail=f"Escolha um tamanho para {produto.nome}")
            nomes_tamanhos = {t.nome.strip().upper(): t.nome.strip() for t in produto.tamanhos}
            if tamanho_escolhido.upper() not in nomes_tamanhos:
                raise HTTPException(
                    status_code=400,
                    detail=f"Tamanho inválido para {produto.nome}. Tamanhos disponíveis: {', '.join(nomes_tamanhos.values())}",
                )
            tamanho_escolhido = nomes_tamanhos[tamanho_escolhido.upper()]
        else:
            tamanho_escolhido = None

        produto.estoque -= item.quantidade
        total += produto.preco * item.quantidade
        itens.append(
            models.ItemPedido(
                produto_id=produto.id,
                quantidade=item.quantidade,
                preco_unitario=produto.preco,
                tamanho=tamanho_escolhido,
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
    cancelar_pedidos_vencidos(db)

    pedido = (
        db.query(models.Pedido)
        .filter(models.Pedido.id == pedido_id, models.Pedido.cliente_id == cliente.id)
        .first()
    )
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    if pedido.status == "cancelado":
        raise HTTPException(status_code=400, detail="Pedido cancelado por falta de pagamento. Faça um novo pedido.")

    itens = [
        {
            "titulo": f"{item.produto.nome} - {item.tamanho}" if item.tamanho else item.produto.nome,
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
        if pedido is None:
            return {"ok": True}

        if pedido.status == "cancelado":
            print(f"ATENÇÃO: pagamento aprovado para pedido cancelado #{pedido.id}. Verificar reembolso.")
            return {"ok": True}

        if pedido.status != "pago":
            pedido.status = "pago"
            db.commit()

    return {"ok": True}