"""shop-api: la tienda de juguete (FastAPI). Llama al servicio payments para cobrar."""

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.db import Item, Order, SessionLocal

app = FastAPI()


@app.get("/items")
def list_items(limit: int = 20):
    with SessionLocal() as db:
        return db.scalars(select(Item).limit(limit)).all()


@app.get("/items/{item_id}")
def get_item(item_id: int):
    with SessionLocal() as db:
        return db.get(Item, item_id)


@app.post("/orders")
def create_order(item_id: int, amount: int):
    with SessionLocal() as db:
        order = Order(item_id=item_id, amount=amount)
        db.add(order)
        db.commit()
    httpx.post("http://payments:3000/charges", json={"order": order.id, "amount": amount}, timeout=5)
    return {"id": order.id}
