"""
HiLark Lark Webhook & Event Router
===================================
Vị trí: server/routers/lark.py

Mục đích:
    Cung cấp endpoint Webhook cho Lark Open Platform:
      - POST /api/lark/events            : Nhận sự kiện (query-param ?app_id=cli_xxx hoặc không có param).
      - POST /api/lark/events/{app_id}   : Path-based route — tiện cho proxy/firewall cấm query string.
      - POST /api/lark/card-action       : Card Action Callback (query-param ?app_id=cli_xxx hoặc không có param).
      - POST /api/lark/card-action/{app_id}: Path-based route cho Card Action.

Quy tắc định danh tenant (theo EDL-0072):
    1. Path param `{app_id}` được ưu tiên cao nhất; nó được inject vào query_params để
       messenger.py dùng chung 1 đường logic (tránh duplicate code).
    2. Query param `?app_id=cli_...` được xử lý tiếp theo.
    3. Nếu không có param nào, messenger sẽ fallback theo thứ tự updated_at.
"""

from fastapi import APIRouter, Request, Response
from starlette.datastructures import QueryParams

from services.lark import lark_service

router = APIRouter(prefix="/api/lark", tags=["Lark Integration"])


def _inject_app_id(request: Request, app_id: str) -> Request:
    """
    Tạo bản sao Request với app_id đã được inject vào query_params.

    Path-based routes (/events/{app_id}) cần forward app_id sang messenger mà không
    duplicate toàn bộ logic giải mã/định tuyến. Cách đơn giản nhất là ghi đè
    request.query_params để messenger.py đọc được ``request.query_params.get("app_id")``.
    """
    scope = dict(request.scope)
    raw_qs = request.scope.get("query_string", b"") or b""
    if raw_qs:
        new_qs = raw_qs + f"&app_id={app_id}".encode()
    else:
        new_qs = f"app_id={app_id}".encode()
    scope["query_string"] = new_qs
    return Request(scope, request.receive, request._send)


@router.post("/events", summary="Lark Event Subscription Webhook")
async def handle_lark_events(request: Request) -> Response:
    """
    Endpoint nhận tất cả các sự kiện từ Lark Event Subscriptions:
      - Trả về Challenge Code khi Lark gửi request xác thực URL (URL Verification).
      - Nhận và phân phối sự kiện tin nhắn người dùng gửi cho Bot (im.message.receive_v1).
      - Nhận sự kiện tương tác bấm nút trên Thẻ tương tác (card.action.trigger).

    app_id có thể được truyền qua query param ``?app_id=cli_xxx`` để định danh tenant
    tuyệt đối, không cần đoán mò.
    """
    return await lark_service.handle_fastapi_request(request)


@router.post("/events/{app_id}", summary="Lark Event Subscription Webhook (Path-based App ID)")
async def handle_lark_events_by_app_id(app_id: str, request: Request) -> Response:
    """
    Route path-based song song với ``/events?app_id=...``.

    Dùng khi proxy hoặc firewall doanh nghiệp không cho phép query string trên
    Webhook URL. Cấu hình trên Lark Developer Console:
        Request URL: https://<domain>/api/lark/events/<app_id>

    app_id được inject vào query_params để tái sử dụng toàn bộ logic trong messenger.py.
    """
    patched = _inject_app_id(request, app_id)
    return await lark_service.handle_fastapi_request(patched)


@router.post("/card-action", summary="Lark Interactive Card Action Webhook")
async def handle_lark_card_action(request: Request) -> Response:
    """
    Endpoint nhận trực tiếp các sự kiện bấm nút trên Thẻ tương tác (Lark Interactive Card Action Callback).

    app_id có thể được truyền qua query param ``?app_id=cli_xxx`` để định danh đúng
    runtime client của tenant cần xử lý callback.
    """
    return await lark_service.handle_card_action_request(request)


@router.post("/card-action/{app_id}", summary="Lark Interactive Card Action Webhook (Path-based App ID)")
async def handle_lark_card_action_by_app_id(app_id: str, request: Request) -> Response:
    """
    Route path-based song song với ``/card-action?app_id=...``.

    Dùng khi proxy hoặc firewall doanh nghiệp không cho phép query string trên
    Card Action URL. Cấu hình trên Lark Developer Console (Callback Configuration):
        Card Request URL: https://<domain>/api/lark/card-action/<app_id>

    app_id được inject vào query_params để tái sử dụng toàn bộ logic trong messenger.py.
    """
    patched = _inject_app_id(request, app_id)
    return await lark_service.handle_card_action_request(patched)
