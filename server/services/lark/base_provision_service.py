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

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

from core.config import settings
from core.tenant_errors import TenantContextMissing, TokenUnavailable
from database.db import get_system_config_collection
from database.scoped_query import get_current_tenant_key
from models.memory import get_vietnam_now_iso
from models.system_config import SystemBaseConfigRecord

logger = logging.getLogger("hilark.base_provision")


class BaseProvisionService:
    """Quản trị cấu hình và tự động khởi tạo Lark Base Quản trị Doanh nghiệp."""

    def __init__(self):
        self._cached_config: Optional[SystemBaseConfigRecord] = None

    def _get_tenant_access_token(
        self,
        tenant_key: Optional[str] = None,
    ) -> str:
        """Bot Tenant Access Token — luôn qua token_broker của đúng tenant."""
        eff_tenant = tenant_key or get_current_tenant_key()
        from services.auth.tenant_token_manager import token_broker

        return token_broker.get_token_sync(eff_tenant, "bot")

    async def _get_tenant_access_token_async(
        self,
        tenant_key: Optional[str] = None,
    ) -> str:
        """Phiên bản async: luôn đi qua token_broker trên token loop duy nhất."""
        eff_tenant = tenant_key or get_current_tenant_key()
        from services.auth.tenant_token_manager import token_broker

        return await token_broker.get(eff_tenant, "bot")

    async def get_active_base_config(
        self,
        force_refresh: bool = False,
        tenant_key: Optional[str] = None,
    ) -> SystemBaseConfigRecord:
        """
        Lấy cấu hình Lark Base đang hoạt động, **chỉ từ MongoDB**:
          - Có tenant_key: đọc document `tenants` của chính tenant đó.
          - Không có tenant_key: đọc document `system_config/lark_base_config`.
          - Chưa có ở cả hai: trả bản ghi rỗng để caller báo "chưa setup".

        Trước đây tầng cuối cùng của chuỗi là `.env` kèm table id hardcode
        `"tblZphzEZPLQAy24"`. Nó khiến một tenant chưa setup Base âm thầm đọc/ghi
        vào Base của đơn vị khác, nên bị bỏ hoàn toàn.
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
                        provisioned_by="auto_provision",
                    )
            except Exception as e:
                logger.warning(f"Lỗi khi đọc base config từ tenant '{eff_tenant}': {e}")
            return SystemBaseConfigRecord(
                config_key=f"tenant_base_{eff_tenant}",
                tenant_key=eff_tenant,
                app_token="",
                app_url="",
                chat_scope_table_id="",
                policy_table_id="",
                is_auto_provisioned=False,
                provisioned_by="",
            )

        if self._cached_config and not force_refresh:
            return self._cached_config

        coll = get_system_config_collection()
        doc = await coll.find_one({"config_key": "lark_base_config"})
        if doc:
            doc.pop("_id", None)
            rec = SystemBaseConfigRecord(**doc)
            self._cached_config = rec
            return rec

        # Không có bản ghi nào trong MongoDB: trả cấu hình rỗng.
        # Caller quyết định "chưa setup"; tuyệt đối không vay app_token/table_id từ .env.
        logger.info(
            "Chưa tìm thấy cấu hình Base trong MongoDB (tenant='%s', system_config/lark_base_config=None).",
            eff_tenant or "default",
        )
        rec = SystemBaseConfigRecord(
            config_key="lark_base_config",
            tenant_key="default",
            app_token="",
            app_url="",
            chat_scope_table_id="",
            policy_table_id="",
            is_auto_provisioned=False,
            provisioned_by="",
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
            logger.info("[BASE_PROVISION] reused tenant=%s url=%s", eff_tenant, existing.app_url)
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

            logger.info("[BASE_PROVISION] app_created app_token=%s default_table=%s", new_app_token, default_table_id)

            # 3. Cấu hình sạch đẹp Bảng 1: Danh mục Dự án & Nhóm chat
            chat_scope_table_id = default_table_id
            if chat_scope_table_id:
                patch_tbl_url = f"{domain}/open-apis/bitable/v1/apps/{new_app_token}/tables/{chat_scope_table_id}"
                await client.patch(patch_tbl_url, headers=headers, json={"name": "Danh mục Dự án & Nhóm chat"})

                # 3.1 Dọn dẹp trường mặc định của Lark: Tái sử dụng Primary field thành 'Dự án / Nhóm', xóa các cột rác
                fields_url = f"{domain}/open-apis/bitable/v1/apps/{new_app_token}/tables/{chat_scope_table_id}/fields"
                try:
                    f_list_res = await client.get(fields_url, headers=headers)
                    existing_flds = f_list_res.json().get("data", {}).get("items", [])
                    for ef in existing_flds:
                        fid = ef.get("field_id")
                        if ef.get("is_primary"):
                            # Đổi tên Primary field thành 'Dự án / Nhóm'
                            try:
                                await client.put(f"{fields_url}/{fid}", headers=headers, json={"field_name": "Dự án / Nhóm"})
                            except Exception as pe:
                                logger.warning(f"Lỗi khi đổi tên Primary field Bảng 1: {pe}")
                        else:
                            # Xóa các cột mẫu thừa (Single option, Date, Attachment, Text)
                            fname = ef.get("field_name", "")
                            if fname in ("Single option", "Date", "Attachment", "Text"):
                                try:
                                    await client.delete(f"{fields_url}/{fid}", headers=headers)
                                except Exception as de:
                                    logger.warning(f"Lỗi khi xóa cột mẫu thừa {fname}: {de}")
                except Exception as clean_err:
                    logger.warning(f"Chưa thể dọn dẹp các trường mặc định Bảng 1: {clean_err}")

                # 3.2 Tạo các trường dữ liệu chuẩn cho Bảng 1 đồng thời (tránh tạo trùng)
                scope_fields = [
                    {"field_name": "Chat ID", "type": 1},  # Text
                    {"field_name": "Người phụ trách", "type": 1},  # Text
                    {
                        "field_name": "Cấp độ bảo mật",
                        "type": 3,  # SingleSelect
                        "property": {"options": [{"name": "standard"}, {"name": "confidential"}]},
                    },
                    {"field_name": "Danh mục tài liệu", "type": 1},  # Text / Link
                    {"field_name": "Nhãn cấm xem", "type": 1},  # Text - Forbidden keywords (comma-separated)
                    {
                        "field_name": "Trạng thái hoạt động",
                        "type": 3,  # SingleSelect
                        "property": {
                            "options": [{"name": "active"}, {"name": "archived"}],
                            "default_value": "active"  # Default to active for new rows
                        },
                    },
                ]
                try:
                    f_refresh_res = await client.get(fields_url, headers=headers)
                    curr_names = {f.get("field_name") for f in f_refresh_res.json().get("data", {}).get("items", [])}
                except Exception:
                    curr_names = set()

                needed_scope_fields = [f for f in scope_fields if f["field_name"] not in curr_names]
                if needed_scope_fields:
                    await asyncio.gather(
                        *[client.post(fields_url, headers=headers, json=fld) for fld in needed_scope_fields],
                        return_exceptions=True,
                    )

                # 3.3 Xóa các dòng trống mặc định do Lark tạo sẵn
                rec_url = f"{domain}/open-apis/bitable/v1/apps/{new_app_token}/tables/{chat_scope_table_id}/records"
                try:
                    r_list_res = await client.get(f"{rec_url}?page_size=50", headers=headers)
                    init_recs = r_list_res.json().get("data", {}).get("items", [])
                    init_empty_ids = [r["record_id"] for r in init_recs if not r.get("fields", {}).get("Chat ID")]
                    if init_empty_ids:
                        await client.post(f"{rec_url}/batch_delete", headers=headers, json={"records": init_empty_ids})
                except Exception as del_rec_err:
                    logger.warning(f"Chưa thể xóa dòng trống Bảng 1: {del_rec_err}")

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

                # 4.1 Đổi tên Primary field mặc định (thường là tiếng Trung 多行文本) thành 'Tên văn bản / Quy định'
                try:
                    p_fld_res = await client.get(policy_fields_url, headers=headers)
                    p_flds = p_fld_res.json().get("data", {}).get("items", [])
                    for pf_item in p_flds:
                        if pf_item.get("is_primary"):
                            await client.put(f"{policy_fields_url}/{pf_item['field_id']}", headers=headers, json={"field_name": "Tên văn bản / Quy định"})
                            break
                except Exception as p_clean_err:
                    logger.warning(f"Chưa thể đổi tên Primary field Bảng 2: {p_clean_err}")

                # 4.2 Đổi tên View mặc định (thường là 表格视图 1) thành 'Tất cả Chính sách'
                try:
                    p_view_res = await client.get(f"{domain}/open-apis/bitable/v1/apps/{new_app_token}/tables/{policy_table_id}/views", headers=headers)
                    p_views = p_view_res.json().get("data", {}).get("items", [])
                    if p_views:
                        await client.patch(f"{domain}/open-apis/bitable/v1/apps/{new_app_token}/tables/{policy_table_id}/views/{p_views[0]['view_id']}", headers=headers, json={"view_name": "Tất cả Chính sách"})
                except Exception as v_clean_err:
                    logger.warning(f"Chưa thể đổi tên View Bảng 2: {v_clean_err}")

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
                await asyncio.gather(
                    *[client.post(policy_fields_url, headers=headers, json=pf) for pf in pol_fields],
                    return_exceptions=True,
                )

                # 4.3 Xóa các dòng trống mặc định do Lark tạo sẵn ở Bảng 2
                pol_rec_url = f"{domain}/open-apis/bitable/v1/apps/{new_app_token}/tables/{policy_table_id}/records"
                try:
                    p_rec_res = await client.get(f"{pol_rec_url}?page_size=50", headers=headers)
                    p_init_recs = p_rec_res.json().get("data", {}).get("items", [])
                    p_empty_ids = [r["record_id"] for r in p_init_recs if not r.get("fields", {}).get("Tên văn bản / Quy định")]
                    if p_empty_ids:
                        await client.post(f"{pol_rec_url}/batch_delete", headers=headers, json={"records": p_empty_ids})
                except Exception as del_p_err:
                    logger.warning(f"Chưa thể xóa dòng trống Bảng 2: {del_p_err}")

                # 4.4 Nạp bản ghi Sổ tay chính sách mẫu vào dòng 1
                try:
                    await client.post(
                        pol_rec_url,
                        headers=headers,
                        json={
                            "fields": {
                                "Tên văn bản / Quy định": "Sổ tay Chính sách & Quy định Công ty",
                                "Phân loại": "Nhân sự",
                                "Văn bản đính kèm / Link": "04_So_tay_chinh_sach_cong_ty.pdf",
                                "Trạng thái áp dụng": "active",
                            }
                        },
                    )
                except Exception as pe:
                    logger.warning(f"Lỗi khi nạp chính sách mẫu: {pe}")

            # 5. Phân quyền và mở liên kết cho Base
            try:
                # 5.1 Cập nhật liên kết công khai trong tổ chức có quyền chỉnh sửa (tenant_editable)
                public_perm_url = f"{domain}/open-apis/drive/v1/permissions/{new_app_token}/public?type=bitable"
                await client.patch(public_perm_url, headers=headers, json={"link_share_entity": "tenant_editable"})
                logger.info("[BASE_PROVISION] public_permission_updated app_token=%s link_share=tenant_editable", new_app_token)
            except Exception as pub_err:
                logger.warning(f"Chưa thể cập nhật public permission cho Base: {pub_err}")

            if admin_open_id:
                try:
                    # 5.2 Cấp quyền Full Access cho Admin
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
                    logger.info("[BASE_PROVISION] admin_full_access_granted app_token=%s admin=%s", new_app_token, admin_open_id)

                    # 5.3 Chuyển giao quyền Sở hữu (Transfer Ownership) cho Admin
                    transfer_url = f"{domain}/open-apis/drive/v1/permissions/{new_app_token}/members/transfer_owner?type=bitable"
                    await client.post(
                        transfer_url,
                        headers=headers,
                        json={
                            "member_type": "openid",
                            "member_id": admin_open_id,
                        },
                    )
                    logger.info("[BASE_PROVISION] ownership_transferred app_token=%s admin=%s", new_app_token, admin_open_id)
                except Exception as perm_err:
                    logger.warning(f"Lỗi khi phân quyền Admin trên Base: {perm_err}")

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
                t_update = {
                    "tenant_key": eff_tenant,
                    "bitable_app_token": new_app_token,
                    "bitable_app_url": config_record.app_url,
                    "chat_scope_table_id": chat_scope_table_id,
                    "company_policy_table_id": policy_table_id,
                }
                if admin_open_id:
                    t_update["admin_open_id"] = admin_open_id
                await upsert_tenant_config(t_update)
                logger.info("[BASE_PROVISION] config_saved tenant=%s collection=tenants", eff_tenant)
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

        # Kích hoạt toàn bộ luồng kết nối & đồng bộ dữ liệu thời gian thực cho Base mới.
        # KHÔNG ghi `app_token`/`table_id` lên singleton `lark_base_service` nữa: Base này
        # thuộc về tenant vừa được cấp phát, còn singleton thì mọi tenant cùng dùng.
        try:
            from services.lark.bitable import LarkBaseService
            from services.lark import lark_service
            from services.knowledge.chat_scopes import scope_service

            if not eff_tenant or eff_tenant == "default":
                logger.info(
                    "[BASE_PROVISION] immediate_sync_skipped reason=missing_tenant",
                )
            else:
                base_service = LarkBaseService(
                    tenant_key=eff_tenant,
                    app_token=new_app_token,
                    table_id=chat_scope_table_id,
                )
                logger.info(
                    "[BASE_PROVISION] client_initialized tenant=%s app_token=%s table=%s",
                    eff_tenant, new_app_token, chat_scope_table_id,
                )

                # Resolver đang giữ cấu hình Base cũ của tenant này -> bỏ cache.
                try:
                    from services.tenancy.tenant_resolver import tenant_resolver
                    tenant_resolver.invalidate(eff_tenant)
                except Exception as inv_err:
                    logger.debug("[BASE_PROVISION] resolver_invalidate_failed tenant=%s error=%s", eff_tenant, inv_err)

                # 1. Đăng ký handler bắt sự kiện Base thay đổi
                lark_service.register_bitable_record_handler(scope_service.handle_bitable_record_changed_event)

                # 2. Đăng ký lắng nghe sự kiện thay đổi trên Lark Cloud (Subscribe Drive API)
                asyncio.create_task(asyncio.to_thread(base_service.subscribe_events, new_app_token))

                # 3. Quét và đồng bộ danh sách nhóm chat của bot vào Base mới
                asyncio.create_task(asyncio.to_thread(base_service.sync_bot_chats))

                # 4. Đồng bộ chính sách & tài liệu từ Base vào WeKnora & MongoDB
                asyncio.create_task(scope_service.sync_all_groups_from_base(tenant_key=eff_tenant))
                logger.info("[BASE_PROVISION] sync_triggered tenant=%s app_token=%s", eff_tenant, new_app_token)
        except Exception as conn_err:
            logger.warning(f"Chưa thể kết nối runtime Base ngay lập tức: {conn_err}")

        return config_record

    async def repair_enterprise_base_schema(self, tenant_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Dọn dẹp và chuẩn hóa cấu trúc schema của Lark Base đã tạo:
          1. Xóa các cột mẫu thừa (Text, Single option, Date, Attachment) ở Bảng 1 nếu có cột chuẩn.
          2. Đổi tên Primary field Bảng 2 nếu đang là tiếng Trung '多行文本' -> 'Tên văn bản / Quy định'.
          3. Đổi tên View Bảng 2 nếu đang là '表格视图 1' -> 'Tất cả Chính sách'.
        """
        eff_tenant = tenant_key or get_current_tenant_key()
        cfg = await self.get_active_base_config(tenant_key=eff_tenant)
        if not cfg or not cfg.app_token:
            return {"success": False, "message": "Không tìm thấy cấu hình Base để sửa."}

        token = await self._get_tenant_access_token_async(eff_tenant)
        if not token:
            return {"success": False, "message": "Không thể lấy Tenant Token."}

        domain = getattr(settings, "LARK_DOMAIN", "https://open.larksuite.com").rstrip("/")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        repaired_actions = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Dọn dẹp Bảng 1 (Dự án & Nhóm chat)
            if cfg.chat_scope_table_id:
                flds_url = f"{domain}/open-apis/bitable/v1/apps/{cfg.app_token}/tables/{cfg.chat_scope_table_id}/fields"
                try:
                    res = await client.get(flds_url, headers=headers)
                    flds = res.json().get("data", {}).get("items", [])
                    has_proper_primary = any(f.get("is_primary") and f.get("field_name") in ("Dự án / Nhóm", "Tên dự án") for f in flds)
                    for f in flds:
                        fid = f.get("field_id")
                        fname = f.get("field_name", "")
                        if f.get("is_primary") and fname in ("Text", "多行文本", "Tên"):
                            try:
                                await client.put(f"{flds_url}/{fid}", headers=headers, json={"field_name": "Dự án / Nhóm"})
                                repaired_actions.append(f"Đổi tên primary field Bảng 1: {fname} -> 'Dự án / Nhóm'")
                            except Exception as pe:
                                logger.debug(f"repair primary field error: {pe}")
                        elif not f.get("is_primary") and fname in ("Single option", "Date", "Attachment", "Text"):
                            try:
                                await client.delete(f"{flds_url}/{fid}", headers=headers)
                                repaired_actions.append(f"Xóa cột mẫu thừa Bảng 1: {fname}")
                            except Exception as de:
                                logger.debug(f"repair delete field error: {de}")
                except Exception as e:
                    logger.warning(f"Lỗi khi dọn dẹp Bảng 1 trong repair: {e}")

            # 2. Dọn dẹp Bảng 2 (Chính sách & Quy định)
            if cfg.policy_table_id:
                p_flds_url = f"{domain}/open-apis/bitable/v1/apps/{cfg.app_token}/tables/{cfg.policy_table_id}/fields"
                try:
                    res2 = await client.get(p_flds_url, headers=headers)
                    flds2 = res2.json().get("data", {}).get("items", [])
                    for f in flds2:
                        fid = f.get("field_id")
                        fname = f.get("field_name", "")
                        if f.get("is_primary") and fname in ("多行文本", "Text"):
                            try:
                                await client.put(f"{p_flds_url}/{fid}", headers=headers, json={"field_name": "Tên văn bản / Quy định"})
                                repaired_actions.append(f"Đổi tên primary field Bảng 2: {fname} -> 'Tên văn bản / Quy định'")
                            except Exception as pe:
                                logger.debug(f"repair policy primary field error: {pe}")
                except Exception as e:
                    logger.warning(f"Lỗi khi dọn dẹp Bảng 2 trong repair: {e}")

                # View Bảng 2
                try:
                    v_res = await client.get(f"{domain}/open-apis/bitable/v1/apps/{cfg.app_token}/tables/{cfg.policy_table_id}/views", headers=headers)
                    views = v_res.json().get("data", {}).get("items", [])
                    for v in views:
                        vid = v.get("view_id")
                        vname = v.get("view_name", "")
                        if vname in ("表格视图 1", "Grid"):
                            try:
                                await client.patch(f"{domain}/open-apis/bitable/v1/apps/{cfg.app_token}/tables/{cfg.policy_table_id}/views/{vid}", headers=headers, json={"view_name": "Tất cả Chính sách"})
                                repaired_actions.append(f"Đổi tên view Bảng 2: {vname} -> 'Tất cả Chính sách'")
                            except Exception as ve:
                                logger.debug(f"repair view error: {ve}")
                except Exception as e:
                    logger.warning(f"Lỗi khi sửa view Bảng 2 trong repair: {e}")

        logger.info("[BASE_PROVISION] schema_repaired actions=%s", repaired_actions)
        return {"success": True, "actions": repaired_actions}


base_provision_service = BaseProvisionService()

__all__ = ["BaseProvisionService", "base_provision_service"]

