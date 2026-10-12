import os
import mercadopago

sdk = mercadopago.SDK(os.environ["MP_ACCESS_TOKEN"])


def criar_link_pagamento(pedido_id: int, itens: list[dict]) -> str:
    """
    itens: lista de dicionários com 'titulo', 'quantidade' e 'preco_unitario'.
    Retorna a URL de pagamento do Mercado Pago.
    """
    base = os.environ.get("PUBLIC_URL", "http://127.0.0.1:8000")

    dados = {
        "items": [
            {
                "title": item["titulo"],
                "quantity": item["quantidade"],
                "unit_price": float(item["preco_unitario"]),
                "currency_id": "BRL",
            }
            for item in itens
        ],
        "external_reference": str(pedido_id),
        "back_urls": {
            "success": f"{base}/vitrine",
            "failure": f"{base}/vitrine",
            "pending": f"{base}/vitrine",
        },
    }

    if os.environ.get("PUBLIC_URL"):
        dados["notification_url"] = f"{base}/webhook/mercadopago"

    resposta = sdk.preference().create(dados)
    return resposta["response"]["init_point"]


def consultar_pagamento(payment_id: str) -> dict:
    return sdk.payment().get(payment_id)["response"]


def consultar_pedido_mp(merchant_order_id: str) -> dict:
    return sdk.merchant_order().get(merchant_order_id)["response"]