"""
HiLark - WeKnora Multi-Tenant Provisioning Service (EDL-0020)
=============================================================
Vị trí: server/services/knowledge/weknora_provision_service.py

Chịu trách nhiệm:
  1. Khởi tạo WeKnora Tenant riêng cho từng doanh nghiệp qua WeKnora API.
  2. Tạo bộ 2 Knowledge Bases tiêu chuẩn:
     - Policy KB (Chính sách & Quy định công ty)
     - Wiki KB (Nhật ký & Daily Digests)
  3. Cấp phát tài khoản WeKnora Web cho Admin (Giải pháp B):
     - Sinh mật khẩu ngẫu nhiên an toàn (chữ hoa, thường, số, ký tự đặc biệt).
  4. Đóng gói thông tin bàn giao (Handover Message) gửi qua Lark DM
     và dữ liệu Screen Guide cho Onboarding Web Wizard.
  5. Hỗ trợ Graceful Mock/Dry-run khi chạy unit tests hoặc WeKnora chưa online.
"""

from __future__ import annotations

import logging
import os
import random
import string
import uuid
from typing import Any, Dict, List, Optional
import httpx

from core.config import settings
from database.db import get_tenant_config, upsert_tenant_config
from models.memory import get_vietnam_now_iso
from models.tenant import TenantConfigRecord, WeKnoraAdminCredentials

logger = logging.getLogger("hilark.weknora_provision")


class WeKnoraProvisionError(RuntimeError):
    """Provisioning không hoàn tất trên WeKnora thật."""


def generate_secure_password(length: int = 12) -> str:
    """Sinh chuỗi mật khẩu ngẫu nhiên an toàn đáp ứng tiêu chuẩn RBAC."""
    upper = random.choice(string.ascii_uppercase)
    lower = random.choice(string.ascii_lowercase)
    digit = random.choice(string.digits)
    special = random.choice("@#$%^&*")
    all_chars = string.ascii_letters + string.digits + "@#$%^&*"
    remaining = [random.choice(all_chars) for _ in range(length - 4)]
    password_list = [upper, lower, digit, special] + remaining
    random.shuffle(password_list)
    return "".join(password_list)


class WeKnoraProvisionService:
    """Dịch vụ tự động cấp phát WeKnora Tenant và Knowledge Bases cho Doanh nghiệp."""

    def __init__(self):
        self.base_url = getattr(settings, "BASE_URL", "http://localhost/api/v1").rstrip("/")
        self.api_key = getattr(settings, "WEKNORA_API_KEY", "")
        self.web_url = getattr(settings, "WEKNORA_WEB_URL", "http://localhost/login").rstrip("/")
        self.dry_run = bool(getattr(settings, "WEKNORA_PROVISION_DRY_RUN", False))

    def _get_headers(self, tenant_id: Optional[int] = None, token: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif self.api_key:
            headers["X-API-Key"] = self.api_key
        if tenant_id:
            headers["X-Tenant-ID"] = str(tenant_id)
        return headers

    async def provision_tenant_weknora(
        self,
        tenant_key: str,
        enterprise_name: Optional[str] = None,
        admin_email: Optional[str] = None,
        admin_open_id: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> TenantConfigRecord:
        """
        Cấp phát toàn bộ tài nguyên WeKnora cho một doanh nghiệp:
          1. Kiểm tra trong MongoDB xem đã được cấp phát chưa (tránh tạo đúp).
          2. Gọi WeKnora API tạo WeKnora Tenant.
          3. Khởi tạo 2 KB chuẩn (Chính sách & Wiki Digests).
          4. Cấp thông tin tài khoản Admin WeKnora Web (Giải pháp B).
          5. Lưu trữ cấu hình bền vững vào MongoDB collection 'tenants'.
        """
        if not tenant_key:
            raise ValueError("Thiếu tenant_key để khởi tạo WeKnora.")

        ent_name = enterprise_name or f"Enterprise {tenant_key[:8]}"

        # 1. Kiểm tra cấu hình đã có trước đó
        existing = await get_tenant_config(tenant_key)
        if existing and existing.get("weknora_tenant_id") and existing.get("weknora_wiki_dataset_id"):
            admin_user_data = existing.get("weknora_admin_user")
            if not admin_user_data or not isinstance(admin_user_data, dict) or not admin_user_data.get("username") or not admin_user_data.get("initial_password"):
                raise WeKnoraProvisionError(
                    f"Tenant '{tenant_key}' đã tồn tại nhưng thiếu credential WeKnora; "
                    "không thể tự sinh password chỉ trong MongoDB. Cần reset/re-provision user trên WeKnora."
                )
            logger.info(f"✔ Doanh nghiệp '{tenant_key}' đã có sẵn WeKnora Tenant: {existing.get('weknora_tenant_id')}")
            return TenantConfigRecord(**existing)

        # 2. Sinh thông tin tài khoản WeKnora Admin (Giải pháp B)
        # WeKnora /auth/login nhận email, vì vậy credential bàn giao cũng dùng email làm định danh đăng nhập.
        username = admin_email or f"admin_{tenant_key[:8]}@hilark.internal"
        account_username = f"admin_{tenant_key[:8]}"
        initial_password = f"HLK@{generate_secure_password(10)}"
        admin_credentials = WeKnoraAdminCredentials(
            username=username,
            initial_password=initial_password,
            web_url=self.web_url,
        )

        weknora_tenant_id: Optional[int] = None
        policy_kb_id: Optional[str] = None
        wiki_kb_id: Optional[str] = None
        default_kb_id: Optional[str] = None

        # 3. Gọi WeKnora API. Offline chỉ được phép khi bật dry-run một cách tường minh.
        async def _do_provision(http_client: httpx.AsyncClient):
            nonlocal weknora_tenant_id, policy_kb_id, wiki_kb_id, default_kb_id
            # 3.1 Tạo user; WeKnora tự tạo personal workspace và trả tenant_id.
            reg_resp = await http_client.post(
                f"{self.base_url}/auth/register",
                json={"username": account_username, "email": username, "password": initial_password},
                timeout=5.0,
            )
            if reg_resp.status_code not in (200, 201, 400):
                raise WeKnoraProvisionError(f"WeKnora register failed: HTTP {reg_resp.status_code}")

            # 3.2 Đăng nhập bằng email để xác minh credential và tenant thật.
            login_resp = await http_client.post(
                f"{self.base_url}/auth/login",
                json={"email": username, "password": initial_password},
                timeout=5.0,
            )
            if login_resp.status_code != 200:
                raise WeKnoraProvisionError(f"WeKnora login verification failed: HTTP {login_resp.status_code}")

            login_data = login_resp.json() or {}
            auth_token = str(login_data.get("token") or (login_data.get("data") or {}).get("token") or "")
            user_obj = login_data.get("user") or (login_data.get("data") or {}).get("user") or {}
            active_tenant = login_data.get("active_tenant") or login_data.get("tenant") or {}
            raw_tenant_id = user_obj.get("tenant_id") or active_tenant.get("id")
            if raw_tenant_id is None:
                raise WeKnoraProvisionError("WeKnora login response thiếu tenant_id")
            weknora_tenant_id = int(raw_tenant_id)
            kb_headers = self._get_headers(tenant_id=weknora_tenant_id, token=auth_token)

            # 3.3 Tạo 3 KB trong tenant vừa xác minh.
            kb1_resp = await http_client.post(
                f"{self.base_url}/knowledge-bases",
                headers=kb_headers,
                json={
                    "name": f"HiLark - {ent_name} - Chính Sách",
                    "description": "Kho quy định và chính sách dùng chung toàn công ty",
                },
                timeout=3.0,
            )
            if kb1_resp.status_code not in (200, 201):
                raise WeKnoraProvisionError(f"WeKnora policy KB creation failed: HTTP {kb1_resp.status_code}")
            kb1_data = kb1_resp.json() or {}
            policy_kb_id = str(kb1_data.get("id") or kb1_data.get("data", {}).get("id") or "")
            if not policy_kb_id:
                raise WeKnoraProvisionError("WeKnora policy KB response thiếu id")

            # 3.4 Tạo KB 2 (Wiki & Digests): POST /api/v1/knowledge-bases
            kb2_resp = await http_client.post(
                f"{self.base_url}/knowledge-bases",
                headers=kb_headers,
                json={
                    "name": f"HiLark - {ent_name} - Wiki & Digests",
                    "description": "Kho nhật ký công việc và Daily Digests chi tiết",
                },
                timeout=3.0,
            )
            if kb2_resp.status_code not in (200, 201):
                raise WeKnoraProvisionError(f"WeKnora wiki KB creation failed: HTTP {kb2_resp.status_code}")
            kb2_data = kb2_resp.json() or {}
            wiki_kb_id = str(kb2_data.get("id") or kb2_data.get("data", {}).get("id") or "")
            if not wiki_kb_id:
                raise WeKnoraProvisionError("WeKnora wiki KB response thiếu id")

            # 3.5 Tạo KB 3 (Dự án chung mặc định)
            kb3_resp = await http_client.post(
                f"{self.base_url}/knowledge-bases",
                headers=kb_headers,
                json={
                    "name": f"HiLark - {ent_name} - Dự Án Mặc Định",
                    "description": "Kho tài liệu dự án mặc định cho các nhóm chat chưa cấu hình",
                },
                timeout=3.0,
            )
            if kb3_resp.status_code not in (200, 201):
                raise WeKnoraProvisionError(f"WeKnora default KB creation failed: HTTP {kb3_resp.status_code}")
            kb3_data = kb3_resp.json() or {}
            default_kb_id = str(kb3_data.get("id") or kb3_data.get("data", {}).get("id") or "")
            if not default_kb_id:
                raise WeKnoraProvisionError("WeKnora default KB response thiếu id")

        try:
            if client is not None:
                await _do_provision(client)
            else:
                async with httpx.AsyncClient(timeout=15.0) as http_client:
                    await _do_provision(http_client)
        except Exception as provision_err:
            if not self.dry_run:
                logger.error(f"WeKnora provisioning failed for tenant '{tenant_key}': {provision_err}")
                raise
            logger.warning(f"WEKNORA_PROVISION_DRY_RUN=true, dùng dữ liệu giả cho tenant '{tenant_key}': {provision_err}")

        # 4. Fallback chỉ dùng khi WEKNORA_PROVISION_DRY_RUN=true.
        if not weknora_tenant_id:
            weknora_tenant_id = int(abs(hash(tenant_key)) % 90000 + 10000)
        if not policy_kb_id:
            policy_kb_id = f"kb_policy_{tenant_key[:8]}_{uuid.uuid4().hex[:6]}"
        if not wiki_kb_id:
            wiki_kb_id = f"kb_wiki_{tenant_key[:8]}_{uuid.uuid4().hex[:6]}"
        if not default_kb_id:
            default_kb_id = f"kb_default_{tenant_key[:8]}_{uuid.uuid4().hex[:6]}"

        # 5. Lưu trữ cấu hình bền vững vào MongoDB
        tenant_dict = existing or {}
        tenant_dict.update({
            "tenant_key": tenant_key,
            "enterprise_name": ent_name,
            "weknora_tenant_id": weknora_tenant_id,
            "weknora_policy_dataset_id": policy_kb_id,
            "weknora_wiki_dataset_id": wiki_kb_id,
            "weknora_default_dataset_id": default_kb_id,
            "weknora_admin_user": admin_credentials.to_dict(),
            "status": tenant_dict.get("status") or "active",
        })

        saved_doc = await upsert_tenant_config(tenant_dict)
        logger.info(
            f"🎉 Đã cấp phát WeKnora Tenant thành công cho '{ent_name}': "
            f"tenant_id={weknora_tenant_id}, wiki_kb={wiki_kb_id}, policy_kb={policy_kb_id}"
        )
        return TenantConfigRecord(**saved_doc)

    def build_handover_message(self, tenant_config: TenantConfigRecord) -> str:
        """Đóng gói văn bản bàn giao gửi trực tiếp qua Lark DM cho Admin (Giải pháp B)."""
        creds = tenant_config.weknora_admin_user
        username = creds.username if creds else "Chưa thiết lập"
        password = creds.initial_password if creds else "Chưa thiết lập"
        web_url = creds.web_url if creds else self.web_url
        bitable_url = tenant_config.bitable_app_url or "Đang khởi tạo trên Lark Drive..."

        msg = (
            "📋 THÔNG TIN BÀN GIAO KHÔNG GIAN HILARK CHO DOANH NGHIỆP\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Kính gửi Quản trị viên {tenant_config.enterprise_name or ''},\n"
            "Hệ thống HiLark đã tự động khởi tạo hoàn tất hạ tầng AI cho doanh nghiệp của bạn:\n\n"
            "1. 📂 TRUNG TÂM QUẢN TRỊ DỰ ÁN & NHÓM CHAT (LARK BASE)\n"
            f"   • Đường dẫn: {bitable_url}\n"
            "   • Vị trí: Lưu trực tiếp trong Lark Drive của bạn.\n"
            "   • Chức năng: Thêm nhóm chat, gán tài liệu dự án, cấu hình mức độ bảo mật.\n\n"
            "2. 🌐 KHÔNG GIAN BÁCH KHOA TOÀN THƯ WIKI & DIGESTS (WEKNORA WEB)\n"
            f"   • Đường dẫn Web   : {web_url}\n"
            f"   • Tên đăng nhập   : {username}\n"
            f"   • Mật khẩu ban đầu: {password}\n"
            "   • Chức năng: Đọc lại toàn văn các bản tổng hợp công việc (Daily Digests) chi tiết từng ngày/tuần.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👉 Bước tiếp theo: Thêm bot HiLark vào các nhóm chat cần hỗ trợ để kích hoạt tự động."
        )
        return msg

    def build_screen_guide_data(self, tenant_config: TenantConfigRecord | Dict[str, Any]) -> Dict[str, Any]:
        """Đóng gói dữ liệu hiển thị trên Screen Guide của Onboarding Web Wizard."""
        if isinstance(tenant_config, dict):
            tenant_config = TenantConfigRecord.from_dict(tenant_config)
        creds = tenant_config.weknora_admin_user
        web_url = (creds.web_url if creds and creds.web_url else self.web_url) or "http://localhost/login"
        username = creds.username if creds else ""
        password = creds.initial_password if creds else ""

        return {
            "enterprise_name": tenant_config.enterprise_name,
            "tenant_key": tenant_config.tenant_key,
            "admin_username": username,
            "admin_password": password,
            "weknora_url": self.base_url,
            "weknora_login_url": web_url,
            "policy_dataset_id": tenant_config.weknora_policy_dataset_id,
            "wiki_dataset_id": tenant_config.weknora_wiki_dataset_id,
            "is_provisioned": bool(tenant_config.weknora_tenant_id),
            "bitable": {
                "app_token": tenant_config.bitable_app_token,
                "url": tenant_config.bitable_app_url,
                "status": "ready" if tenant_config.bitable_app_token else "pending",
            },
            "weknora": {
                "tenant_id": tenant_config.weknora_tenant_id,
                "policy_dataset_id": tenant_config.weknora_policy_dataset_id,
                "wiki_dataset_id": tenant_config.weknora_wiki_dataset_id,
                "web_url": web_url,
                "username": username,
                "initial_password": password,
                "status": "ready" if tenant_config.weknora_tenant_id else "pending",
            },
            "status": "success",
            "message": "Không gian tri thức WeKnora và Lark Base đã sẵn sàng.",
        }


# Singleton instance
weknora_provision_service = WeKnoraProvisionService()
