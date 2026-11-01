"""
HiLark - Lark Base (Bitable) Auto-Provisioning & Dynamic Configuration Service
==============================================================================
Vị trí: server/services/lark/base_provision_service.py

Mục đích:
  1. Phân giải Cấu hình Base Động (Dynamic Resolution):
     - Ưu tiên đọc từ MongoDB collection 'system_config'.
     - Fallback an toàn về file .env (LARK_BASE_APP_TOKEN, LARK_BASE_TABLE_ID).
  2. Tự động Khởi tạo 100% Lark Base Doanh nghiệp (Zero-Touch Provisioning):
     - Gọi Lark OpenAPI tạo Bitable App mới.
     - Thiết lập bảng 1: 'Danh mục Dự án & Nhóm chat' (chat_scopes).
     - Thiết lập bảng 2: 'Chính sách & Quy định Công ty' (company_policies).
     - Nạp dữ liệu mẫu 3 dự án (Atlas, Pulse, Sentinel) và Sổ tay chính sách.
     - Phân quyền Full Access (Owner) cho Sếp/Admin trên Lark Drive.
     - Lưu trữ kết quả bền vững vào MongoDB và cập nhật cache trong RAM.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

from core.config import settings
from database.db import get_system_config_collection
from database.scoped_query import get_current_tenant_key
from models.memory import get_vietnam_now_iso
from models.system_config import SystemBaseConfigRecord

logger = logging.getLogger("hilark.base_provision")


class BaseProvisionService:
    """Quản trị cấu hình và tự động khởi tạo Lark Base Quản trị Doanh nghiệp."""

    def __init__(self):
        self._cached_config: Optional[SystemBaseConfigRecord] = None

    def _get_tenant_access_token(self, tenant_key: Optional[str] = None) -> str:
        """Lấy Bot Tenant Access Token qua singleton lark_base_service hoặc auth endpoint."""
        eff_tenant = tenant_key or get_current_tenant_key()
        try:
            from services.lark.bitable import lark_base_service
            token = lark_base_service.get_tenant_access_token(tenant_key=eff_tenant)
            if token:
                return token
        except Exception:
            pass

        # Nếu đang ở ISV Mode và có tenant_key
        if getattr(settings, "IS_ISV_MODE", False) and eff_tenant:
            try:
                from services.auth.isv_token_service import isv_token_service
                token = isv_token_service.get_cached_tenant_token(eff_tenant)
                if token:
                    return token
            except Exception:
                pass

        # Fallback gọi trực tiếp API Lark Auth
        domain = getattr(settings, "LARK_DOMAIN", "https://open.larksuite.com")
        app_id = getattr(settings, "LARK_APP_ID", "") or os.getenv("LARK_APP_ID", "")
        app_secret = getattr(settings, "LARK_APP_SECRET", "") or os.getenv("LARK_APP_SECRET", "")
        if not app_id or not app_secret:
            return ""

        try:
            resp = httpx.post(
                f"{domain}/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
                timeout=10.0,
            )
            data = resp.json()
            if data.get("code") == 0:
                return data.get("tenant_access_token", "")
        except Exception as e:
            logger.error(f"Lỗi khi lấy tenant access token cho base provisioning: {e}")
        return ""

    async def _get_tenant_access_token_async(self, tenant_key: Optional[str] = None) -> str:
        """Lấy Bot Tenant Access Token bất đồng bộ (hỗ trợ ISV Token Service tự làm mới)."""
        eff_tenant = tenant_key or get_current_tenant_key()
        if getattr(settings, "IS_ISV_MODE", False) and eff_tenant:
            try:
                from services.auth.isv_token_service import isv_token_service
                token = await isv_token_service.get_tenant_access_token(eff_tenant)
                if token:
                    return token
            except Exception as e:
                logger.warning(f"Lỗi khi lấy ISV tenant token cho base provisioning: {e}")
        return self._get_tenant_access_token(tenant_key=eff_tenant)

    async def get_active_base_config(
        self,
        force_refresh: bool = False,
        tenant_key: Optional[str] = None,
    ) -> SystemBaseConfigRecord:
        """
        Lấy cấu hình Lark Base đang hoạt động:
          - Nếu có tenant_key: Ưu tiên đọc từ MongoDB collection 'tenants'.
          - Nếu không có: Kiểm tra trong MongoDB collection 'system_config'.
          - Nếu chưa có -> Tạo đối tượng mặc định từ file .env.
        """
        eff_tenant = tenant_key or get_current_tenant_key()

        # Kiểm tra trong tenants collection nếu có tenant_key
        if eff_tenant and eff_tenant != "default":
            try:
                from database.db import get_tenant_config
                t_doc = await get_tenant_config(eff_tenant)
                if t_doc and t_doc.get("bitable_app_token"):
                    domain = getattr(settings, "LARK_DOMAIN", "https://open.larksuite.com")
                    app_tok = t_doc["bitable_app_token"]
                    return SystemBaseConfigRecord(
                        config_key=f"tenant_base_{eff_tenant}",
                        tenant_key=eff_tenant,
                        app_token=app_tok,
                        app_url=t_doc.get("bitable_app_url") or f"{domain}/base/{app_tok}",
                        chat_scope_table_id=t_doc.get("chat_scope_table_id") or "",
                        policy_table_id=t_doc.get("company_policy_table_id") or "",
                        is_auto_provisioned=True,
                        provisioned_by="isv_auto_provision",
                    )
            except Exception as e:
                logger.warning(f"Lỗi khi đọc base config từ tenant '{eff_tenant}': {e}")

        if self._cached_config and not force_refresh:
            return self._cached_config

        coll = get_system_config_collection()
        doc = await coll.find_one({"config_key": "lark_base_config"})
        if doc:
            doc.pop("_id", None)
            rec = SystemBaseConfigRecord(**doc)
            self._cached_config = rec
            return rec

        # Fallback cấu hình mặc định từ .env
        default_app_token = getattr(settings, "LARK_BASE_APP_TOKEN", "") or os.getenv("LARK_BASE_APP_TOKEN", "") or os.getenv("app_token", "")
        default_table_id = getattr(settings, "LARK_BASE_TABLE_ID", "") or os.getenv("LARK_BASE_TABLE_ID", "") or os.getenv("table_id", "")
        default_policy_table_id = getattr(settings, "LARK_BASE_POLICY_TABLE_ID", "") or os.getenv("LARK_BASE_POLICY_TABLE_ID", "") or os.getenv("policy_table_id", "") or "tblZphzEZPLQAy24"
        domain = getattr(settings, "LARK_DOMAIN", "https://open.larksuite.com")
        
        fallback_url = f"{domain}/base/{default_app_token}" if default_app_token else ""

        rec = SystemBaseConfigRecord(
            config_key="lark_base_config",
            tenant_key="default",
            app_token=default_app_token,
            app_url=fallback_url,
            chat_scope_table_id=default_table_id,
            policy_table_id=default_policy_table_id,
            is_auto_provisioned=False,
            provisioned_by="system_env",
        )
        self._cached_config = rec
        return rec

    async def get_chat_scope_target(self, tenant_key: Optional[str] = None) -> Tuple[str, str]:
        """Trả về cặp (app_token, chat_scope_table_id) hiệu lực."""
        cfg = await self.get_active_base_config(tenant_key=tenant_key)
        return cfg.app_token, cfg.chat_scope_table_id

    async def get_policy_target(self, tenant_key: Optional[str] = None) -> Tuple[str, str]:
        """Trả về cặp (app_token, policy_table_id) hiệu lực."""
        cfg = await self.get_active_base_config(tenant_key=tenant_key)
        return cfg.app_token, cfg.policy_table_id

    async def provision_enterprise_base(
        self,
        admin_open_id: Optional[str] = None,
        base_name: str = "HiLark - Trung Tâm Quản Trị Dự Án & Chính Sách Doanh Nghiệp",
        tenant_key: Optional[str] = None,
    ) -> SystemBaseConfigRecord:
        """
        Tự động 100% khởi tạo Lark Base Doanh nghiệp qua OpenAPI:
          1. Kiểm tra Base đã tồn tại chưa (tránh tạo trùng).
          2. Gọi POST /open-apis/bitable/v1/apps tạo Base mới với token của tenant.
          3. Cấu hình Bảng 1: 'Danh mục Dự án & Nhóm chat' kèm các cột chuẩn.
          4. Cấu hình Bảng 2: 'Chính sách & Quy định Công ty' kèm các cột chuẩn.
          5. Nạp dữ liệu mẫu 3 dự án và Sổ tay chính sách.
          6. Phân quyền Full Access cho Admin trên Drive.
          7. Lưu trữ cấu hình vào MongoDB (tenants collection nếu multi-tenant) và đồng bộ singleton.
        """
        eff_tenant = tenant_key or get_current_tenant_key()

        # 1. Nếu đã tự động tạo trước đó -> tái sử dụng
        existing = await self.get_active_base_config(tenant_key=eff_tenant)
        if existing and existing.is_auto_provisioned and existing.app_token:
            logger.info(f"✔ Đã tồn tại Lark Base quản trị tự động cho tenant '{eff_tenant}': {existing.app_url}")
            return existing

        token = await self._get_tenant_access_token_async(eff_tenant)
        if not token:
            raise ValueError(f"Không thể lấy Tenant Access Token để khởi tạo Lark Base cho tenant '{eff_tenant}'.")

        domain = getattr(settings, "LARK_DOMAIN", "https://open.larksuite.com").rstrip("/")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 2. Tạo Bitable App mới
            create_app_url = f"{domain}/open-apis/bitable/v1/apps"
            app_resp = await client.post(create_app_url, headers=headers, json={"name": base_name, "folder_token": ""})
            app_data = app_resp.json()
            if app_data.get("code") != 0 or not app_data.get("data", {}).get("app"):
                err_msg = app_data.get("msg") or app_resp.text
                logger.error(f"Lỗi khi tạo Bitable App qua Lark API: {err_msg}")
                raise RuntimeError(f"Lark API không thể tạo Base: {err_msg}")

            app_info = app_data["data"]["app"]
            new_app_token = app_info.get("app_token")
            new_app_url = app_info.get("url")
            default_table_id = app_info.get("default_table_id")

            logger.info(f"🎉 Đã khởi tạo Bitable App thành công: app_token={new_app_token}, default_table={default_table_id}")

            # 3. Đổi tên và thêm trường cho Bảng 1: Danh mục Dự án & Nhóm chat
            chat_scope_table_id = default_table_id
            if chat_scope_table_id:
                patch_tbl_url = f"{domain}/open-apis/bitable/v1/apps/{new_app_token}/tables/{chat_scope_table_id}"
                await client.patch(patch_tbl_url, headers=headers, json={"name": "Danh mục Dự án & Nhóm chat"})

                # Tạo các trường dữ liệu chuẩn cho Bảng 1
                fields_url = f"{domain}/open-apis/bitable/v1/apps/{new_app_token}/tables/{chat_scope_table_id}/fields"
                scope_fields = [
                    {"field_name": "Chat ID", "type": 1},  # Text
                    {"field_name": "Tên dự án", "type": 1},  # Text
                    {"field_name": "Người phụ trách", "type": 1},  # Text
                    {
                        "field_name": "Cấp độ bảo mật",
                        "type": 3,  # SingleSelect
                        "property": {"options": [{"name": "standard"}, {"name": "confidential"}]},
                    },
                    {"field_name": "Danh mục tài liệu", "type": 1},  # Text / Link
                    {
                        "field_name": "Trạng thái hoạt động",
                        "type": 3,  # SingleSelect
                        "property": {"options": [{"name": "active"}, {"name": "archived"}]},
                    },
                ]
                for fld in scope_fields:
                    try:
                        await client.post(fields_url, headers=headers, json=fld)
                    except Exception as fe:
                        logger.warning(f"Không thể tạo trường {fld.get('field_name')}: {fe}")

                # Nạp 3 dự án mẫu của đề bài
                rec_url = f"{domain}/open-apis/bitable/v1/apps/{new_app_token}/tables/{chat_scope_table_id}/records"
                baseline_projects = [
                    {
                        "fields": {
                            "Chat ID": "oc_atlas_group",
                            "Tên dự án": "Project Atlas",
                            "Người phụ trách": "Trần Tuấn",
                            "Cấp độ bảo mật": "standard",
                            "Danh mục tài liệu": "Project_Charter.docx, Code_of_Conduct.docx",
                            "Trạng thái hoạt động": "active",
                        }
                    },
                    {
                        "fields": {
                            "Chat ID": "oc_pulse_group",
                            "Tên dự án": "Project Pulse",
                            "Người phụ trách": "Lê Hoàng",
                            "Cấp độ bảo mật": "standard",
                            "Danh mục tài liệu": "Project_Charter.docx",
                            "Trạng thái hoạt động": "active",
                        }
                    },
                    {
                        "fields": {
                            "Chat ID": "oc_sentinel_group",
                            "Tên dự án": "Project Sentinel",
                            "Người phụ trách": "Phạm Minh",
                            "Cấp độ bảo mật": "confidential",
                            "Danh mục tài liệu": "Project_Charter.docx",
                            "Trạng thái hoạt động": "active",
                        }
                    },
                ]
                for p in baseline_projects:
                    try:
                        await client.post(rec_url, headers=headers, json=p)
                    except Exception as pe:
                        logger.warning(f"Lỗi khi nạp bản ghi dự án mẫu: {pe}")

            # 4. Tạo Bảng 2: Chính sách & Quy định Công ty
            create_tbl_url = f"{domain}/open-apis/bitable/v1/apps/{new_app_token}/tables"
            tbl2_resp = await client.post(
                create_tbl_url,
                headers=headers,
                json={"table": {"name": "Chính sách & Quy định Công ty"}},
            )
            tbl2_data = tbl2_resp.json()
            policy_table_id = tbl2_data.get("data", {}).get("table_id") or "tbl_policies"

            if policy_table_id and policy_table_id != "tbl_policies":
                policy_fields_url = f"{domain}/open-apis/bitable/v1/apps/{new_app_token}/tables/{policy_table_id}/fields"
                pol_fields = [
                    {
                        "field_name": "Phân loại",
                        "type": 3,
                        "property": {"options": [{"name": "Nhân sự"}, {"name": "Tài chính"}, {"name": "Bảo mật"}, {"name": "Vận hành"}]},
                    },
                    {"field_name": "Văn bản đính kèm / Link", "type": 1},
                    {"field_name": "Ngày ban hành", "type": 5},  # Date
                    {
                        "field_name": "Trạng thái áp dụng",
                        "type": 3,
                        "property": {"options": [{"name": "active"}, {"name": "superseded"}]},
                    },
                ]
                for pf in pol_fields:
                    try:
                        await client.post(policy_fields_url, headers=headers, json=pf)
                    except Exception as pe:
                        logger.warning(f"Không thể tạo trường chính sách: {pe}")

                # Nạp bản ghi Sổ tay chính sách
                pol_rec_url = f"{domain}/open-apis/bitable/v1/apps/{new_app_token}/tables/{policy_table_id}/records"
                try:
                    await client.post(
                        pol_rec_url,
                        headers=headers,
                        json={
                            "fields": {
                                "Phân loại": "Nhân sự",
                                "Văn bản đính kèm / Link": "04_So_tay_chinh_sach_cong_ty.pdf",
                                "Trạng thái áp dụng": "active",
                            }
                        },
                    )
                except Exception as pe:
                    logger.warning(f"Lỗi khi nạp chính sách mẫu: {pe}")

            # 5. Phân quyền Full Access (Owner) cho Admin nếu có
            if admin_open_id:
                try:
                    perm_url = f"{domain}/open-apis/drive/v1/permissions/{new_app_token}/members?type=bitable"
                    await client.post(
                        perm_url,
                        headers=headers,
                        json={
                            "member_type": "openid",
                            "member_id": admin_open_id,
                            "perm": "full_access",
                        },
                    )
                    logger.info(f"✔ Đã cấp quyền Full Access cho Admin: {admin_open_id} trên Base {new_app_token}")
                except Exception as perm_err:
                    logger.warning(f"Chưa thể gán quyền trực tiếp qua Drive Permission API: {perm_err}")

        # 6. Lưu bản ghi cấu hình vào MongoDB
        now_iso = get_vietnam_now_iso()
        config_record = SystemBaseConfigRecord(
            config_key=f"tenant_base_{eff_tenant}" if eff_tenant else "lark_base_config",
            tenant_key=eff_tenant or "default",
            app_token=new_app_token,
            app_url=new_app_url or f"{domain}/base/{new_app_token}",
            chat_scope_table_id=chat_scope_table_id,
            policy_table_id=policy_table_id,
            is_auto_provisioned=True,
            provisioned_by=admin_open_id,
            provisioned_at=now_iso,
            updated_at=now_iso,
        )

        if eff_tenant and eff_tenant != "default":
            try:
                from database.db import upsert_tenant_config
                await upsert_tenant_config({
                    "tenant_key": eff_tenant,
                    "bitable_app_token": new_app_token,
                    "bitable_app_url": config_record.app_url,
                    "chat_scope_table_id": chat_scope_table_id,
                    "company_policy_table_id": policy_table_id,
                })
                logger.info(f"✔ Đã lưu cấu hình Bitable vào collection 'tenants' cho tenant '{eff_tenant}'")
            except Exception as e:
                logger.error(f"Lỗi khi lưu cấu hình Base vào tenant '{eff_tenant}': {e}")
        else:
            coll = get_system_config_collection()
            await coll.update_one(
                {"config_key": "lark_base_config"},
                {"$set": config_record.to_dict()},
                upsert=True,
            )
            # Cập nhật cache singleton trong RAM cho single-tenant
            self._cached_config = config_record

        # Đồng bộ ngược vào singleton lark_base_service
        try:
            from services.lark.bitable import lark_base_service
            lark_base_service.app_token = new_app_token
            lark_base_service.table_id = chat_scope_table_id
            logger.info("✔ Đã đồng bộ app_token & table_id mới vào singleton lark_base_service")
        except Exception:
            pass

        return config_record


base_provision_service = BaseProvisionService()

__all__ = ["BaseProvisionService", "base_provision_service"]

