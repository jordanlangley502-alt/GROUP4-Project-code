from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from backend.security import require
from .schemas import MenuItemResponse, OrderCreate, OrderResponse
from .service import create_order, get_menu, list_orders, ensure_pos_schema, order_detail


router = APIRouter(prefix="/api")


@router.get("/menu", response_model=list[MenuItemResponse])
def menu(request: Request):
    ensure_pos_schema(request.app.state.database)
    return get_menu(request.app.state.database)


@router.post("/orders", response_model=OrderResponse, status_code=201)
def place_order(
    body: OrderCreate,
    request: Request,
    response: Response,
    user=Depends(require("Cashier")),
):
    try:
        order, status = create_order(request.app.state.database, body, user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if status == 200:
        response.status_code = 200
        return order
    # 201 is FastAPI's normal success status for this route.
    return order


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: int, request: Request):
    order = order_detail(request.app.state.database, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    return order


@router.get("/orders", response_model=list[OrderResponse])
def get_orders(
    request: Request,
    status: str | None = Query(default=None, pattern="^(Confirmed|Making|Ready)$"),
    order_type: str | None = Query(default=None, pattern="^(dine_in|takeout|delivery)$"),
):
    return list_orders(request.app.state.database, status=status, order_type=order_type)
