"""
HiLark - One-Click Setup Orchestration Service
=============================================
Vị trí: server/services/setup/one_click_setup_service.py

Mục đích:
  Điều phối tự động 100% luồng thiết lập 7 bước của HiLark theo chuẩn ISV SaaS:
    1. Admin mở HiLark Setup (Landing Page).
    2. Lark Authorization (Admin ủy quyền qua OAuth).
    3. HiLark Backend nhận authorization (Đổi code lấy token, bóc tách tenant_key & admin_open_id).
    4. Tự động kích hoạt Bot (Sử dụng App Bot có sẵn của hệ thống).
    5. Đồng bộ cấu hình & Cấp phát hạ tầng (Lark Base + WeKnora Knowledge Space).
    6. Gửi tin nhắn kiểm tra (Gửi Interactive Card chào mừng tới Lark DM của Admin).
    7. Ready (Bàn giao hệ thống hoàn tất, sẵn sàng vận hành).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument

from core.config import settings
from database.db import get_setup_sessions_collection, get_tenants_collection, get_system_config_collection
from models.memory import get_vietnam_now_iso
from services.auth_service import token_service
from services.user_settings_service import user_settings_service

logger = logging.getLogger("hilark.setup.one_click")


STEP_DEFINITIONS = [
    {
        "step": 1,
        "title": "Admin mở HiLark Setup",
        "description": "Admin nhấn Install HiLark và bắt đầu quy trình cài đặt.",
    },
    {
        "step": 2,
        "title": "Ủy quyền tenant & user",
        "description": "Admin cài ứng dụng cho doanh nghiệp và cấp quyền OAuth bắt buộc để HiLark nhận diện tenant, access token và refresh token.",
    },
    {
        "step": 3,
        "title": "Xác thực App & token",
        "description": "HiLark xác thực App credential, lấy tenant access token và lưu user access/refresh token an toàn.",
    },
    {
        "step": 4,
        "title": "Xác nhận quyền Bot",
        "description": "Dùng tenant access token để gọi Lark API; Bot dùng danh nghĩa ứng dụng, không giả danh user.",
    },
    {
        "step": 5,
        "title": "Đồng bộ cấu hình & Cấp phát hạ tầng",
        "description": "Tự động thiết lập Lark Base Quản trị và Không gian Tri thức WeKnora.",
    },
    {
        "step": 6,
        "title": "Gửi tin nhắn kiểm tra",
        "description": "HiLark gửi tin nhắn chào mừng và thông báo kết nối thành công tới Admin qua Lark Chat.",
    },
    {
        "step": 7,
        "title": "Ready",
        "description": "Toàn bộ hệ thống sẵn sàng. Admin có thể bắt đầu sử dụng HiLark.",
    },
]


class OneClickSetupService:
    """Service quản lý trạng thái và thực thi luồng One-Click Setup 7 bước."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._tasks: Dict[str, Dict[str, Any]] = {}

    def create_task(self, app_registration_id: Optional[str] = None) -> str:
        """Tạo phiên cài đặt mới với 7 bước khởi đầu."""
        task_id = str(uuid.uuid4())
        steps = []
        for step_def in STEP_DEFINITIONS:
            steps.append({
                "step": step_def["step"],
                "title": step_def["title"],
                "description": step_def["description"],
                "status": "pending",  # pending | processing | completed | failed
                "detail": "",
                "updated_at": get_vietnam_now_iso(),
            })

        # Bước 1 hoàn thành khi mở trang setup
        steps[0]["status"] = "completed"
        steps[0]["detail"] = "Đã kết nối trang thiết lập HiLark."

        # Bước 2 đang chờ ủy quyền
        steps[1]["status"] = "processing"
        steps[1]["detail"] = "Đang chuyển hướng sang Lark OAuth để cấp quyền..."

        self._tasks[task_id] = {
            "task_id": task_id,
            "status": "in_progress",  # in_progress | completed | failed
            "current_step": 2,
            "steps": steps,
            "tenant_info": {},
            "app_registration_id": app_registration_id,
            "error": None,
            "created_at": get_vietnam_now_iso(),
            "updated_at": get_vietnam_now_iso(),
        }
        return task_id

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Lấy thông tin tiến độ của một task."""
        return self._tasks.get(task_id)

    async def persist_task(self, task_id: str, oauth_state: Optional[str] = None) -> None:
        """Lưu session/progress để callback và polling không phụ thuộc process hiện tại."""
        task = self._tasks.get(task_id)
        if not task:
            return
        now = datetime.now(timezone.utc)
        if oauth_state:
            task["oauth_state_hash"] = hashlib.sha256(oauth_state.encode()).hexdigest()
        task["updated_at"] = get_vietnam_now_iso()
        doc = {
            "task_id": task_id,
            "status": task.get("status", "in_progress"),
            "current_step": task.get("current_step", 2),
            "steps": task.get("steps", []),
            "tenant_info": task.get("tenant_info", {}),
            "app_registration_id": task.get("app_registration_id"),
            "error": task.get("error"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "oauth_state_hash": task.get("oauth_state_hash"),
            "state_consumed": task.get("state_consumed", False),
            "expires_at": now + timedelta(hours=2),
        }
        try:
            await get_setup_sessions_collection().update_one(
                {"task_id": task_id},
                {"$set": doc},
                upsert=True,
            )
        except Exception as exc:
            # Giữ flow local/dev hoạt động khi Mongo tạm thời unavailable; production
            # sẽ bắt lỗi này qua health/readiness và log cảnh báo có cấu trúc.
            logger.warning("Không thể persist setup session %s: %s", task_id, exc)
            if getattr(settings, "SETUP_REQUIRE_DURABLE_STATE", False):
                raise

    async def load_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Đọc RAM trước, sau đó fallback Mongo để chịu được restart/scale-out."""
        task = self._tasks.get(task_id)
        if task:
            return task
        try:
            doc = await get_setup_sessions_collection().find_one({"task_id": task_id})
        except Exception as exc:
            logger.warning("Không thể đọc setup session %s từ MongoDB: %s", task_id, exc)
            return None
        if not doc:
            return None
        doc.pop("_id", None)
        self._tasks[task_id] = doc
        return doc

    async def claim_oauth_state(self, state: Optional[str]) -> Optional[str]:
        """Validate và consume state một lần; trả về task_id hợp lệ."""
        if not state or not state.startswith("setup_"):
            return None
        task_id = state[len("setup_"):]
        expected_hash = hashlib.sha256(state.encode()).hexdigest()
        task = self._tasks.get(task_id)
        if task:
            saved_hash = task.get("oauth_state_hash")
            if saved_hash and saved_hash != expected_hash:
                return None
            if task.get("state_consumed"):
                return None
            if not saved_hash:
                # Compatibility với task tạo trong test/dev cũ; task production được
                # persist từ /setup/install nên luôn có hash.
                task["state_consumed"] = True
                return task_id
            task["oauth_state_hash"] = expected_hash
            task["state_consumed"] = True
            await self.persist_task(task_id)
            return task_id

        col = get_setup_sessions_collection()
        doc = await col.find_one_and_update(
            {"task_id": task_id, "oauth_state_hash": expected_hash, "state_consumed": {"$ne": True}},
            {"$set": {"state_consumed": True, "updated_at": get_vietnam_now_iso()}},
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            return None
        doc.pop("_id", None)
        self._tasks[task_id] = doc
        return task_id

    def _update_step(
        self,
        task_id: str,
        step_number: int,
        status: str,
        detail: str = "",
    ) -> None:
        """Cập nhật trạng thái của một bước cụ thể."""
        task = self._tasks.get(task_id)
        if not task:
            return

        for step in task["steps"]:
            if step["step"] == step_number:
                step["status"] = status
                if detail:
                    step["detail"] = detail
                step["updated_at"] = get_vietnam_now_iso()
                break

        task["current_step"] = step_number
        task["updated_at"] = get_vietnam_now_iso()
        # Persist bất đồng bộ để polling từ instance khác nhìn thấy tiến độ.
        try:
            asyncio.get_running_loop().create_task(self.persist_task(task_id))
        except RuntimeError:
            # Khi gọi từ script sync/test không có event loop, trạng thái RAM vẫn hợp lệ.
            pass

    async def run_setup_pipeline(self, task_id: str, code: str, state: Optional[str] = None) -> Dict[str, Any]:
        """
        Thực thi toàn bộ pipeline 7 bước tự động.
        Được gọi ngay khi OAuth callback trả về authorization code.
        """
        task = self._tasks.get(task_id)
        if not task:
            # Tự động tạo task nếu task_id chưa có trong RAM
            task_id = self.create_task()
            task = self._tasks[task_id]

        try:
            logger.info(f"🚀 [ONE-CLICK SETUP] Bắt đầu pipeline cho task '{task_id}' (code: {code[:6]}...)")
            # -------------------------------------------------------------
            # BƯỚC 2: Lark Authorization (Hoàn tất)
            # -------------------------------------------------------------
            self._update_step(
                task_id,
                step_number=2,
                status="completed",
                detail="Admin đã cấp quyền thành công qua Lark OAuth.",
            )

            # -------------------------------------------------------------
            # BƯỚC 3: HiLark Backend nhận authorization & xác thực Tenant
            # -------------------------------------------------------------
            self._update_step(
                task_id,
                step_number=3,
                status="processing",
                detail="Đang đổi authorization code lấy Token và trích xuất thông tin doanh nghiệp...",
            )
            logger.info(f"🔄 [ONE-CLICK SETUP] Task '{task_id}': Đang đổi authorization code...")

            app_registration_id = task.get("app_registration_id")
            app_record = None
            if app_registration_id:
                from services.lark_app_service import lark_app_service
                app_record = await lark_app_service.get_registration(app_registration_id)
                if not app_record:
                    raise RuntimeError("Không tìm thấy Custom App registration của phiên setup.")

            token_res = await token_service.exchange_code_for_token(
                code=code,
                app_id=app_record.get("app_id") if app_record else None,
                app_secret=app_record.get("app_secret") if app_record else None,
            )
            if not token_res.get("access_token") or not token_res.get("refresh_token"):
                raise RuntimeError("OAuth user chưa trả về đủ access_token và refresh_token; không thể hoàn tất setup.")
            admin_open_id = token_res.get("open_id") or getattr(settings, "LARK_USER_OPEN_ID", "") or ""
            admin_name = token_res.get("user_name") or getattr(settings, "LARK_USER_NAME", "") or "Quản trị viên"
            tenant_key = token_res.get("tenant_key") or getattr(settings, "LARK_TENANT_KEY", "") or (f"tenant_{admin_open_id[:8]}" if admin_open_id else "tenant_default")
            if app_record:
                from services.lark_app_service import lark_app_service
                await lark_app_service.link_tenant(app_registration_id, tenant_key, admin_open_id)
            logger.info(f"✔ [ONE-CLICK SETUP] Task '{task_id}': Token exchanged. Admin: {admin_name} ({admin_open_id}), Tenant: {tenant_key}")

            # Lưu hồ sơ Tenant vào MongoDB Atlas
            tenants_col = get_tenants_collection()
            tenant_record = {
                "tenant_key": tenant_key,
                "app_id": (app_record or {}).get("app_id") or getattr(settings, "LARK_APP_ID", ""),
                # Chỉ chuyển sang ready sau khi cả Base và WeKnora hoàn tất.
                "status": "provisioning",
                "admin_open_id": admin_open_id,
                "admin_name": admin_name,
                "installed_at": get_vietnam_now_iso(),
                "updated_at": get_vietnam_now_iso(),
            }
            await tenants_col.update_one(
                {"tenant_key": tenant_key},
                {"$set": tenant_record, "$setOnInsert": {"created_at": get_vietnam_now_iso()}},
                upsert=True,
            )

            # Lưu đồng bộ vào user_settings & runtime LarkService
            try:
                await user_settings_service.save_user_settings(
                    open_id=admin_open_id,
                    user_name=admin_name,
                    tenant_key=tenant_key,
                )
            except Exception as us_err:
                logger.warning(f"Lỗi khi lưu user_settings trong One-Click Setup: {us_err}")

            from services.lark import lark_service
            lark_service.known_user_open_id = admin_open_id

            self._update_step(
                task_id,
                step_number=3,
                status="completed",
                detail=f"Xác thực doanh nghiệp thành công: '{tenant_key}' (Admin: {admin_name}).",
            )

            # -------------------------------------------------------------
            # BƯỚC 4: Tự động kích hoạt Bot
            # -------------------------------------------------------------
            self._update_step(
                task_id,
                step_number=4,
                status="processing",
                detail="Đang kích hoạt Bot mặc định của hệ thống cho doanh nghiệp...",
            )

            # Bot đã được khai báo sẵn trong HiLark App trên Lark Developer Platform
            app_id = (app_record or {}).get("app_id") or getattr(settings, "LARK_APP_ID", "")
            app_secret = (app_record or {}).get("app_secret") or getattr(settings, "LARK_APP_SECRET", "")
            if not app_id or not app_secret:
                raise RuntimeError("Thiếu App ID/App Secret sau bước xác thực App credential.")

            tenant_token_ready = False
            if getattr(settings, "IS_ISV_MODE", False):
                from services.auth.isv_token_service import isv_token_service
                tenant_token = await isv_token_service.get_tenant_access_token(tenant_key)
                tenant_token_ready = bool(tenant_token)
                if not tenant_token_ready:
                    raise RuntimeError("Không lấy được tenant access token cho doanh nghiệp.")
                token_detail = "Tenant access token đã được cấp cho doanh nghiệp."
            else:
                # Custom App lấy tenant token internal ngay trong BaseProvisionService
                # ở bước kế tiếp; không gọi nhầm endpoint ISV với tenant_key.
                tenant_token_ready = True
                token_detail = "App credential hợp lệ; tenant access token internal sẽ được dùng khi tạo Base."

            bot_applink = f"https://applink.larksuite.com/client/bot/open?appId={app_id}"

            self._update_step(
                task_id,
                step_number=4,
                status="completed",
                detail=f"{token_detail} Bot dùng danh nghĩa App; OAuth user vẫn được lưu riêng để gửi dưới danh nghĩa Admin.",
            )

            # -------------------------------------------------------------
            # BƯỚC 5: Đồng bộ cấu hình & Cấp phát hạ tầng (Lark Base + WeKnora)
            # -------------------------------------------------------------
            self._update_step(
                task_id,
                step_number=5,
                status="processing",
                detail="Đang tự động khởi tạo Lark Base và Không gian Tri thức WeKnora...",
            )

            base_result = None
            base_error = None
            weknora_result = None
            weknora_error = None

            async def _init_base():
                nonlocal base_result, base_error
                try:
                    from services.lark.base_provision_service import base_provision_service
                    base_result = await asyncio.wait_for(
                        base_provision_service.provision_enterprise_base(
                            admin_open_id=admin_open_id or None,
                            tenant_key=tenant_key,
                            app_id=app_id or None,
                            app_secret=app_secret or None,
                        ),
                        timeout=20.0,
                    )
                    logger.info(f"✔ [ONE-CLICK SETUP] Auto-provision Lark Base thành công cho tenant '{tenant_key}'")
                except Exception as base_err:
                    base_error = base_err
                    logger.error(f"Lỗi khi khởi tạo Lark Base trong One-Click Setup: {base_err}")

            async def _init_weknora():
                nonlocal weknora_result, weknora_error
                try:
                    from services.knowledge.weknora_provision_service import weknora_provision_service
                    weknora_result = await asyncio.wait_for(
                        weknora_provision_service.provision_tenant_weknora(
                            tenant_key=tenant_key,
                            enterprise_name=f"Doanh nghiệp {tenant_key}",
                            admin_open_id=admin_open_id or None,
                        ),
                        timeout=15.0,
                    )
                    logger.info(f"✔ [ONE-CLICK SETUP] Auto-provision WeKnora thành công cho tenant '{tenant_key}'")
                except Exception as weknora_err:
                    weknora_error = weknora_err
                    logger.error(f"Lỗi khi khởi tạo WeKnora trong One-Click Setup: {weknora_err}")

            # Chạy song song cả hai tác vụ cấp phát hạ tầng để tối ưu tốc độ hoàn thành dưới 5 giây
            await asyncio.gather(_init_base(), _init_weknora(), return_exceptions=True)

            # WeKnora là hạ tầng bắt buộc của luồng bàn giao credential. Không được đánh dấu
            # tenant ready nếu tenant/user/KB chưa được provision thật.
            if weknora_result is None:
                raise RuntimeError(f"WeKnora provisioning chưa hoàn tất: {weknora_error or 'unknown error'}")
            if base_result is None:
                raise RuntimeError(f"Lark Base provisioning chưa hoàn tất: {base_error or 'unknown error'}")

            bitable_url = getattr(base_result, "app_url", "") if base_result else ""
            if not bitable_url:
                domain = getattr(settings, "LARK_DOMAIN", "https://open.larksuite.com")
                app_tok = getattr(settings, "LARK_BASE_APP_TOKEN", "")
                bitable_url = f"{domain}/base/{app_tok}" if app_tok else ""

            weknora_url = getattr(settings, "WEKNORA_WEB_URL", "http://localhost/login")

            self._update_step(
                task_id,
                step_number=5,
                status="completed",
                detail="Đã khởi tạo Lark Base Quản trị và Không gian Tri thức WeKnora thành công.",
            )

            # -------------------------------------------------------------
            # BƯỚC 6: Gửi tin nhắn kiểm tra (Ping DM) tới Admin
            # -------------------------------------------------------------
            self._update_step(
                task_id,
                step_number=6,
                status="processing",
                detail="Đang gửi tin nhắn chào mừng và xác nhận kết nối tới Lark Chat của Admin...",
            )

            ping_sent = False
            if admin_open_id:
                try:
                    from services.lark.card_builder import build_marketplace_welcome_card

                    # Dựng thẻ chào mừng với thông tin tenant đầy đủ từ CSDL
                    tenant_dict = {
                        "tenant_key": tenant_key,
                        "bitable_app_url": bitable_url,
                        "admin_credentials": {
                            "username": f"admin_{tenant_key[:8]}@hilark.internal",
                            "initial_password": "Đã cấu hình",
                            "web_url": weknora_url,
                        },
                    }
                    if weknora_result and hasattr(weknora_result, "model_dump"):
                        tenant_dict.update(weknora_result.model_dump())
                    elif weknora_result and isinstance(weknora_result, dict):
                        tenant_dict.update(weknora_result)

                    # Nạp bản ghi mới nhất từ MongoDB để có đầy đủ weknora_admin_user và bitable_app_url
                    try:
                        from database.db import get_tenant_config
                        saved_t = await get_tenant_config(tenant_key)
                        if saved_t:
                            tenant_dict.update(saved_t)
                    except Exception:
                        pass

                    if bitable_url:
                        tenant_dict["bitable_app_url"] = bitable_url

                    card = build_marketplace_welcome_card(tenant_dict)
                    sender_service = lark_service
                    if app_record:
                        from services.lark_app_service import lark_app_service
                        from services.lark.runtime import get_or_create_lark_service

                        # Dùng đúng Custom App vừa OAuth; singleton legacy có
                        # thể thuộc một App khác và gây open_id cross app.
                        runtime_app = await lark_app_service.get_by_app_id(app_id)
                        if runtime_app:
                            sender_service = await get_or_create_lark_service(runtime_app)
                        else:
                            logger.warning(
                                "Không tìm thấy runtime mapping cho App %s; fallback Lark client mặc định",
                                app_id,
                            )

                    res = await sender_service.send_bot_dm_to_owner(
                        text=card,
                        target_open_id=admin_open_id,
                        tenant_key=tenant_key,
                    )
                    if res.get("success"):
                        ping_sent = True
                        logger.info(f"✔ [ONE-CLICK SETUP] Đã gửi Welcome Card tới Admin {admin_open_id}")
                    else:
                        logger.warning(f"Lark phản hồi gửi tin nhắn: {res.get('msg')}")
                except Exception as ping_err:
                    logger.warning(f"Lỗi khi gửi ping DM tới Admin trong One-Click Setup: {ping_err}")

            ping_detail = "Đã gửi Thẻ chào mừng và bàn giao hệ thống tới Lark DM của Admin." if ping_sent else "Hạ tầng đã sẵn sàng (Admin có thể mở trò chuyện trực tiếp với Bot trên Lark)."
            self._update_step(
                task_id,
                step_number=6,
                status="completed",
                detail=ping_detail,
            )

            # -------------------------------------------------------------
            # BƯỚC 7: Ready
            # -------------------------------------------------------------
            await tenants_col.update_one(
                {"tenant_key": tenant_key},
                {"$set": {"status": "ready", "ready_at": get_vietnam_now_iso()}},
                upsert=True,
            )

            self._update_step(
                task_id,
                step_number=7,
                status="completed",
                detail="Thiết lập hoàn tất 100%. HiLark đã sẵn sàng phục vụ doanh nghiệp!",
            )

            weknora_creds = None
            if weknora_result and hasattr(weknora_result, "admin_credentials") and weknora_result.admin_credentials:
                weknora_creds = {
                    "username": getattr(weknora_result.admin_credentials, "username", ""),
                    "initial_password": getattr(weknora_result.admin_credentials, "initial_password", ""),
                    "web_url": getattr(weknora_result.admin_credentials, "web_url", weknora_url),
                }

            task["status"] = "completed"
            task["tenant_info"] = {
                "tenant_key": tenant_key,
                "admin_name": admin_name,
                "admin_open_id": admin_open_id,
                "app_id": app_id,
                "tenant_token_ready": tenant_token_ready,
                "bot_applink": bot_applink,
                "bitable_app_url": bitable_url,
                "weknora_web_url": weknora_url,
                "weknora_credentials": weknora_creds,
            }
            task["updated_at"] = get_vietnam_now_iso()
            await self.persist_task(task_id)

            return {
                "success": True,
                "task_id": task_id,
                "status": "completed",
                "tenant_info": task["tenant_info"],
            }

        except Exception as e:
            logger.error(f"Lỗi trong One-Click Setup Pipeline: {e}", exc_info=True)
            current_step = task.get("current_step", 3)
            self._update_step(
                task_id,
                step_number=current_step,
                status="failed",
                detail=f"Lỗi xảy ra tại bước này: {str(e)}",
            )
            task["status"] = "failed"
            task["error"] = str(e)
            task["updated_at"] = get_vietnam_now_iso()
            try:
                await self.persist_task(task_id)
            except Exception:
                logger.exception("Không thể lưu trạng thái setup failed vào MongoDB")

            return {
                "success": False,
                "task_id": task_id,
                "status": "failed",
                "error": str(e),
                "failed_at_step": current_step,
            }


# Singleton instance toàn hệ thống
one_click_setup_service = OneClickSetupService()

