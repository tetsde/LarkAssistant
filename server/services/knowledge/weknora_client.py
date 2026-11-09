from contextlib import asynccontextmanager
import logging
import sys
from typing import Any, Dict, List, Optional, Union
import httpx
from fastapi import HTTPException
from core.config import settings
from core.http_client import get_http_client
from models.chat import ChatRequest
from services.ai.text_filter import text_filter

logger = logging.getLogger("hilark.weknora")



class WeKnoraService:
    def __init__(self):
        self.api_key = settings.WEKNORA_API_KEY
        self.base_url = settings.BASE_URL
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }

    @asynccontextmanager
    async def _get_client_session(self, client: Optional[httpx.AsyncClient] = None):
        """Helper lấy HTTP client: ưu tiên persistent pool, tương thích ngược với unit test mock context manager."""
        if client is not None:
            if hasattr(client, "__aenter__") and hasattr(client, "__aexit__"):
                async with client as c:
                    yield c
            else:
                yield client
            return

        # Kiểm tra mock tại httpx hoặc tại consolidated / transitional shim services.knowledge_service.httpx
        shim_mod = sys.modules.get("services.knowledge_service") or sys.modules.get("services.weknora")
        shim_httpx = getattr(shim_mod, "httpx", None) if shim_mod else None
        target_httpx = shim_httpx or httpx

        # Nếu httpx.AsyncClient đã bị monkey-patch / mock trong unit test
        if type(target_httpx.AsyncClient).__name__ in ("MagicMock", "AsyncMock"):
            mock_obj = target_httpx.AsyncClient()
            if hasattr(mock_obj, "__aenter__") and hasattr(mock_obj, "__aexit__"):
                async with mock_obj as c:
                    yield c
                return
            yield mock_obj
            return

        yield get_http_client()

    async def create_session(self, client: Optional[httpx.AsyncClient] = None) -> str:
        try:
            async with self._get_client_session(client) as http_client:
                response = await http_client.post(
                    f"{self.base_url}/sessions",
                    headers=self.headers,
                    json={}
                )
            response.raise_for_status()
            data = response.json()
            
            session_id = data.get("id") or data.get("session_id")
            if not session_id and "data" in data:
                session_id = data["data"].get("id")

            if not session_id:
                raise ValueError(f"Could not find session id in response: {data}")
                
            return session_id
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")

    async def get_chat_response(self, request: ChatRequest, client: Optional[httpx.AsyncClient] = None) -> dict:
        import json
        if not self.api_key or not self.base_url:
            raise HTTPException(status_code=500, detail="Missing environment variables (api_weknora or base_url) in .env")

        # 1. Tạo session
        session_id = await self.create_session(client)
        chat_url = f"{self.base_url}/agent-chat/{session_id}"
        
        # 2. Gọi Agent Chat và hứng dữ liệu qua connection pool
        async with self._get_client_session(client) as stream_client:
            async with stream_client.stream(
                "POST",
                chat_url,
                headers=self.headers,
                json=request.model_dump(), 
                timeout=httpx.Timeout(120.0) # Đợi full câu trả lời có thể lâu hơn
            ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        raise HTTPException(status_code=response.status_code, detail=error_text.decode('utf-8'))
                        
                    # Lọc luồng SSE để lấy dòng final_content cuối cùng
                    final_answer = ""
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data_str = line[5:].strip() # Bỏ chữ "data:"
                            if not data_str:
                                continue
                            try:
                                payload = json.loads(data_str)
                                # Lấy final_content từ event complete
                                if payload.get("response_type") == "complete":
                                    final_answer = payload.get("data", {}).get("final_content", "")
                                    break
                            except json.JSONDecodeError:
                                pass
                    
                    if not final_answer:
                        raise HTTPException(status_code=500, detail="Could not parse final answer from WeKnora SSE stream.")
                        
                    clean_answer = text_filter.clean_output(final_answer)
                    citations = text_filter.extract_kb_citations(final_answer)
                    result_payload = {"session_id": session_id, "answer": clean_answer}
                    if citations:
                        result_payload["citations"] = citations

                    return result_payload

    async def get_kb_info(
        self,
        kb_id: str,
        client: Optional[httpx.AsyncClient] = None,
        tenant_id: Optional[Union[int, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Lấy thông tin chi tiết của Knowledge Base từ WeKnora (ID, Tên, Mô tả).
        Endpoint WeKnora: GET /knowledge-bases/{kb_id}
        Trả về dict: {"id": str, "name": str, "description": str} hoặc None nếu không tồn tại / lỗi.
        """
        if not self.api_key or not self.base_url or not kb_id:
            return None

        clean_id = kb_id.strip()
        url = f"{self.base_url}/knowledge-bases/{clean_id}"
        headers = dict(self.headers)
        if tenant_id:
            headers["X-Tenant-ID"] = str(tenant_id)
        try:
            async with self._get_client_session(client) as http_client:
                resp = await http_client.get(url, headers=headers, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    return {
                        "id": data.get("id", clean_id),
                        "name": data.get("name", ""),
                        "description": data.get("description", ""),
                    }
                return None
        except Exception:
            return None

    def get_configured_kb_ids(self) -> List[str]:
        """
        Lấy danh sách Knowledge Base IDs đã cấu hình từ .env (settings.WEKNORA_DATASET_ID).
        Hỗ trợ phân tách bằng dấu phẩy nếu cấu hình nhiều KB cụ thể.
        Nếu rỗng, trả về list rỗng (KHÔNG tự động quét toàn bộ KB để tránh làm tràn context/nổ token).
        """
        if settings.WEKNORA_DATASET_ID:
            return [kb_id.strip() for kb_id in settings.WEKNORA_DATASET_ID.split(",") if kb_id.strip()]
        return []

    async def save_to_kb(
        self,
        text: str,
        dataset_id: Optional[str] = None,
        name: Optional[str] = None,
        tenant_id: Optional[Union[int, str]] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> dict:
        # `dataset_id` là bắt buộc về hợp đồng: không được mượn kho mặc định từ .env,
        # vì kho đó thuộc về một doanh nghiệp cụ thể.
        target_id = (dataset_id or "").strip()
        if target_id and "," in target_id:
            target_id = target_id.split(",")[0].strip()
        if not target_id:
            raise ValueError(
                "save_to_kb() yêu cầu dataset_id của tenant đang ghi; không dùng "
                "WEKNORA_DATASET_ID mặc định từ .env."
            )
            
        url = f"{self.base_url}/knowledge-bases/{target_id}/knowledge/manual"
        doc_name = name or f"Memory_{text[:15]}..."
        payload = {
            "title": doc_name,
            "content": text,
            "status": "publish",
        }
        headers = dict(self.headers)
        if tenant_id:
            headers["X-Tenant-ID"] = str(tenant_id)

        async with self._get_client_session(client) as http_client:
            response = await http_client.post(url, headers=headers, json=payload, timeout=30.0)
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=f"Failed to save to KB: {response.text}")

            return response.json()

    async def upload_file(
        self,
        file_name: str,
        file_bytes: bytes,
        dataset_id: Optional[str] = None,
        mime_type: str = "application/pdf",
        timeout: float = 60.0,
        tenant_id: Optional[Union[int, str]] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """
        Upload một file tài liệu (PDF, docx, ...) vào Knowledge Base của WeKnora qua endpoint:
        POST /api/v1/knowledge-bases/{dataset_id}/knowledge/file (multipart/form-data)

        Trả về dict kết quả:
          - success: True/False
          - knowledge_id: ID tài liệu WeKnora
          - is_duplicate: True nếu file đã tồn tại trên WeKnora (deduplication 409)
        """
        # `dataset_id` phải do caller cung cấp theo tenant; không fallback .env.
        target_id = (dataset_id or "").strip()
        if target_id and "," in target_id:
            target_id = target_id.split(",")[0].strip()
        if not target_id:
            raise ValueError(
                "upload_file() yêu cầu dataset_id của tenant đang nạp tài liệu; không dùng "
                "WEKNORA_DATASET_ID mặc định từ .env."
            )

        if not self.api_key or not self.base_url:
            raise HTTPException(status_code=500, detail="Missing WeKnora API Key or base_url in .env")

        url = f"{self.base_url}/knowledge-bases/{target_id}/knowledge/file"
        headers = {
            "X-API-Key": self.api_key,
        }
        if tenant_id:
            headers["X-Tenant-ID"] = str(tenant_id)

        files = {
            "file": (file_name, file_bytes, mime_type),
        }
        data = {
            "enable_multimodel": "true",
        }

        try:
            async with self._get_client_session(client) as http_client:
                resp = await http_client.post(url, headers=headers, files=files, data=data, timeout=timeout)
                # 200/201: tạo mới, 409: file đã tồn tại trên WeKnora (deduplication)
                if resp.status_code in (200, 201, 409):
                    res_json = resp.json()
                    doc_data = res_json.get("data", {}) if isinstance(res_json, dict) else {}
                    doc_id = doc_data.get("id") or doc_data.get("knowledge_id", "")
                    doc_summary = doc_data.get("summary") or doc_data.get("description") or None
                    return {
                        "success": True,
                        "knowledge_id": doc_id,
                        "file_name": file_name,
                        "dataset_id": target_id,
                        "is_duplicate": resp.status_code == 409,
                        "summary": doc_summary,
                        "data": doc_data,
                    }
                else:
                    return {
                        "success": False,
                        "error": f"HTTP {resp.status_code}: {resp.text}",
                        "status_code": resp.status_code,
                    }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_document_info(
        self,
        dataset_id: str,
        knowledge_id: str,
        timeout: float = 10.0,
        tenant_id: Optional[Union[int, str]] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Lấy thông tin chi tiết và tóm tắt (summary) của một tài liệu từ WeKnora.
        Endpoint: GET /knowledge/{knowledge_id} hoặc GET /knowledge-bases/{dataset_id}/knowledge/{knowledge_id}
        """
        if not self.api_key or not self.base_url or not knowledge_id:
            return None

        clean_kid = knowledge_id.strip()
        url = f"{self.base_url}/knowledge/{clean_kid}"
        headers = dict(self.headers)
        if tenant_id:
            headers["X-Tenant-ID"] = str(tenant_id)
        try:
            async with self._get_client_session(client) as http_client:
                resp = await http_client.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 404 and dataset_id:
                    # Fallback sang cấu trúc URL cũ nếu WeKnora phiên bản khác
                    alt_url = f"{self.base_url}/knowledge-bases/{dataset_id.strip()}/knowledge/{clean_kid}"
                    resp = await http_client.get(alt_url, headers=headers, timeout=timeout)

                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    return {
                        "id": data.get("id", clean_kid),
                        "title": data.get("title") or data.get("name") or "",
                        "summary": data.get("summary") or data.get("description") or None,
                        "status": data.get("status") or "",
                    }
                return None
        except Exception:
            return None

    async def list_knowledges(
        self,
        dataset_id: str,
        page: int = 1,
        page_size: int = 200,
        tenant_id: Optional[Union[int, str]] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[Dict[str, Any]]:
        """
        Liệt kê danh sách tài liệu hiện có trong Knowledge Base của WeKnora.
        Endpoint WeKnora: GET /knowledge-bases/{dataset_id}/knowledge
        """
        if not self.api_key or not self.base_url or not dataset_id:
            return []

        target_id = dataset_id.strip()
        if "," in target_id:
            target_id = target_id.split(",")[0].strip()

        url = f"{self.base_url}/knowledge-bases/{target_id}/knowledge"
        headers = dict(self.headers)
        if tenant_id:
            headers["X-Tenant-ID"] = str(tenant_id)

        params = {"page": page, "page_size": page_size}
        try:
            async with self._get_client_session(client) as http_client:
                resp = await http_client.get(url, headers=headers, params=params, timeout=20.0)
                if resp.status_code == 200:
                    res_json = resp.json()
                    data = res_json.get("data", []) if isinstance(res_json, dict) else []
                    return data if isinstance(data, list) else []
                logger.warning(f"[WeKnora] list_knowledges HTTP {resp.status_code}: {resp.text}")
                return []
        except Exception as e:
            logger.warning(f"[WeKnora] Lỗi khi list_knowledges (kb={target_id}): {e}")
            return []

    async def delete_knowledge(
        self,
        knowledge_id: str,
        tenant_id: Optional[Union[int, str]] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> bool:
        """
        Xoá một tài liệu khỏi WeKnora qua endpoint: DELETE /knowledge/{knowledge_id}
        Xoá các chunks, vector embeddings và knowledge graph của tài liệu cũ.
        """
        if not self.api_key or not self.base_url or not knowledge_id:
            return False

        clean_kid = knowledge_id.strip()
        url = f"{self.base_url}/knowledge/{clean_kid}"
        headers = dict(self.headers)
        if tenant_id:
            headers["X-Tenant-ID"] = str(tenant_id)

        try:
            async with self._get_client_session(client) as http_client:
                resp = await http_client.delete(url, headers=headers, timeout=20.0)
                if resp.status_code in (200, 204):
                    logger.info("[WEKNORA] knowledge_deleted knowledge_id=%s", clean_kid)
                    return True
                logger.warning("[WEKNORA] knowledge_delete_failed knowledge_id=%s status=%d body=%s", clean_kid, resp.status_code, resp.text)
                return False
        except Exception as e:
            logger.warning(f"[WeKnora] Lỗi khi delete_knowledge({clean_kid}): {e}")
            return False

    async def retrieve(
        self,
        query: str,
        knowledge_base_ids: Optional[List[str]] = None,
        knowledge_ids: Optional[List[str]] = None,
        match_count: int = 5,
        vector_threshold: Optional[float] = None,
        keyword_threshold: Optional[float] = None,
        disable_keywords_match: bool = False,
        disable_vector_match: bool = False,
        rerank_enabled: bool = True,
        timeout: float = 30.0,
        tenant_id: Optional[Union[int, str]] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[Dict[str, Any]]:
        """
        Truy xuất các đoạn văn bản (Chunks) từ Knowledge Base của WeKnora qua endpoint POST /knowledge-search.
        Đây là API thuần RAG Retrieval (không qua LLM, chỉ trả về các đoạn trích dẫn và điểm số).
        Hỗ trợ tham số `knowledge_ids` để giới hạn tìm kiếm trong các file cụ thể của nhóm chat (chống lộ chéo).

        Trả về:
          Danh sách SearchResult dict:
          - id: Chunk ID
          - content: Nội dung văn bản của chunk
          - knowledge_title: Tên tài liệu nguồn (VD: du_an_mau_hilark.pdf)
          - knowledge_id: ID tài liệu
          - score: Điểm tương đồng / Rerank score
          - knowledge_base_id: ID Knowledge Base
        """
        if not self.api_key or not self.base_url:
            raise HTTPException(status_code=500, detail="Missing environment variables (api_weknora or base_url) in .env")

        if not query or not query.strip():
            return []

        search_url = f"{self.base_url}/knowledge-search"

        try:
            async with self._get_client_session(client) as http_client:
                valid_knowledge_ids = [str(kid).strip() for kid in (knowledge_ids or []) if str(kid).strip()]
                target_kbs = knowledge_base_ids or self.get_configured_kb_ids()

                if not valid_knowledge_ids and not target_kbs:
                    logger.warning("[WEKNORA] retrieve_skipped reason=missing_kb_and_knowledge_ids")
                    return []

                shim_mod = sys.modules.get("services.knowledge_service") or sys.modules.get("services.weknora")
                active_settings = getattr(shim_mod, "settings", settings) if shim_mod else settings

                effective_vector_threshold = (
                    active_settings.vector_threshold if vector_threshold is None else vector_threshold
                )
                effective_keyword_threshold = (
                    active_settings.keyword_threshold if keyword_threshold is None else keyword_threshold
                )

                payload: Dict[str, Any] = {
                    "query": query.strip(),
                    "match_count": match_count,
                }

                # ĐẶC BIỆT: Trong WeKnora backend, nếu gửi cả knowledge_base_ids và knowledge_ids,
                # WeKnora sẽ kích hoạt Full KB Search và BỎ QUA knowledge_ids!
                # Do đó: Nếu có knowledge_ids cụ thể (tài liệu của nhóm chat), CHỈ gửi knowledge_ids.
                # Chỉ khi không có knowledge_ids, mới gửi knowledge_base_ids để quét toàn bộ dataset.
                if valid_knowledge_ids:
                    payload["knowledge_ids"] = valid_knowledge_ids
                elif target_kbs:
                    payload["knowledge_base_ids"] = target_kbs

                if effective_vector_threshold is not None:
                    payload["vector_threshold"] = effective_vector_threshold
                if effective_keyword_threshold is not None:
                    payload["keyword_threshold"] = effective_keyword_threshold
                if disable_keywords_match:
                    payload["disable_keywords_match"] = True
                if disable_vector_match:
                    payload["disable_vector_match"] = True
                if not rerank_enabled:
                    payload["rerank"] = {"enabled": False}

                headers = dict(self.headers)
                # P0 FIX #3: Validate tenant_id matches current context to prevent spoofing
                if tenant_id:
                    try:
                        from database.scoped_query import get_current_tenant_key
                        from database.db import get_tenant_config_sync
                        cur_tk = get_current_tenant_key()
                        
                        if cur_tk:
                            # Verify tenant_id matches expected value for current tenant
                            t_cfg = get_tenant_config_sync(cur_tk)
                            expected_tenant_id = t_cfg.get("weknora_tenant_id") if t_cfg else None
                            
                            if expected_tenant_id and str(tenant_id) != str(expected_tenant_id):
                                logger.error(
                                    "[WEKNORA] security_blocked reason=tenant_id_mismatch cur_tenant=%s requested=%s expected=%s",
                                    cur_tk,
                                    tenant_id,
                                    expected_tenant_id,
                                )
                                raise ValueError(f"Tenant ID mismatch: {tenant_id} != {expected_tenant_id}")
                    except Exception as e:
                        if "Tenant ID mismatch" in str(e):
                            raise
                        logger.warning(f"Could not validate tenant_id: {e}")
                    
                    headers["X-Tenant-ID"] = str(tenant_id)
                else:
                    try:
                        from database.scoped_query import get_current_tenant_key
                        from database.db import get_tenant_config_sync
                        cur_tk = get_current_tenant_key()
                        if cur_tk:
                            t_cfg = get_tenant_config_sync(cur_tk)
                            if t_cfg and t_cfg.get("weknora_tenant_id"):
                                headers["X-Tenant-ID"] = str(t_cfg["weknora_tenant_id"])
                    except Exception:
                        pass
                    if "X-Tenant-ID" not in headers:
                        # Không được fallback sang tenant mặc định trong production:
                        # thiếu mapping là lỗi cấu hình, không phải quyền truy cập global.
                        logger.warning("[WEKNORA] retrieve_rejected reason=missing_x_tenant_id")
                        return []

                response = await http_client.post(
                    search_url,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                if response.status_code == 200:
                    data = response.json()
                    # Phản hồi WeKnora chuẩn: {"success": true, "data": [...SearchResult]}
                    if isinstance(data, dict):
                        if "data" in data and isinstance(data["data"], list):
                            return data["data"]
                        elif "records" in data and isinstance(data["records"], list):
                            return data["records"]
                    elif isinstance(data, list):
                        return data
                    return []
                elif response.status_code == 404:
                    # Endpoint fallback nếu /knowledge-search chưa mount: gọi /knowledge-bases/{id}/hybrid-search
                    if target_kbs:
                        fb_url = f"{self.base_url}/knowledge-bases/{target_kbs[0]}/hybrid-search"
                        fb_res = await client.post(fb_url, headers=headers, json=payload)
                        if fb_res.status_code == 200:
                            fb_data = fb_res.json()
                            return fb_data.get("data", []) if isinstance(fb_data, dict) else []
                    return []
                else:
                    logger.warning("[WEKNORA] retrieve_failed status=%s body=%s", response.status_code, response.text)
                    return []
        except Exception as e:
            logger.error("[WEKNORA] retrieve_error error=%s", e)
            return []

    def retrieve_sync(
        self,
        query: str,
        knowledge_base_ids: Optional[List[str]] = None,
        knowledge_ids: Optional[List[str]] = None,
        match_count: int = 5,
        timeout: float = 30.0,
        tenant_id: Optional[Union[int, str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Phiên bản đồng bộ dùng httpx.Client() trực tiếp cho CLI / Scripts kiểm thử.
        """
        if not self.api_key or not self.base_url or not query or not query.strip():
            return []

        search_url = f"{self.base_url}/knowledge-search"
        valid_knowledge_ids = [str(kid).strip() for kid in (knowledge_ids or []) if str(kid).strip()]
        target_kbs = knowledge_base_ids or self.get_configured_kb_ids()
        if not valid_knowledge_ids and not target_kbs:
            logger.warning("[WEKNORA] retrieve_sync_skipped reason=missing_kb_and_knowledge_ids")
            return []

        payload: Dict[str, Any] = {
            "query": query.strip(),
            "match_count": match_count,
        }
        if valid_knowledge_ids:
            payload["knowledge_ids"] = valid_knowledge_ids
        elif target_kbs:
            payload["knowledge_base_ids"] = target_kbs

        headers = dict(self.headers)
        if tenant_id:
            headers["X-Tenant-ID"] = str(tenant_id)
        else:
            try:
                from database.scoped_query import get_current_tenant_key
                from database.db import get_tenant_config_sync
                cur_tk = get_current_tenant_key()
                if cur_tk:
                    t_cfg = get_tenant_config_sync(cur_tk)
                    if t_cfg and t_cfg.get("weknora_tenant_id"):
                        headers["X-Tenant-ID"] = str(t_cfg["weknora_tenant_id"])
            except Exception:
                pass
            if "X-Tenant-ID" not in headers:
                logger.warning("[WEKNORA] retrieve_sync_rejected reason=missing_x_tenant_id")
                return []

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(search_url, headers=headers, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                        return data["data"]
                    return data if isinstance(data, list) else []
                else:
                    logger.warning("[WEKNORA] retrieve_sync_failed status=%s body=%s", response.status_code, response.text)
                    return []
        except Exception as e:
            logger.error("[WEKNORA] retrieve_sync_error error=%s", e)
            return []

    # =========================================================================
    # DATA SOURCE MANAGEMENT (FEISHU / LARK DRIVE & DOCS)
    # =========================================================================

    async def get_datasource_info(
        self, datasource_id: str, client: Optional[httpx.AsyncClient] = None, tenant_id: Optional[Union[int, str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Lấy thông tin chi tiết của một Data Source trong WeKnora.
        Endpoint: GET /datasource/{datasource_id}
        """
        if not self.api_key or not self.base_url or not datasource_id:
            return None

        clean_id = datasource_id.strip()
        url = f"{self.base_url}/datasource/{clean_id}"
        headers = dict(self.headers)
        headers["X-Tenant-ID"] = str(tenant_id) if tenant_id else "10000"
        try:
            async with self._get_client_session(client) as http_client:
                response = await http_client.get(url, headers=headers, timeout=30.0)
                if response.status_code == 200:
                    return response.json()
                logger.warning("[WEKNORA] datasource_info_failed ds_id=%s status=%s body=%s", clean_id, response.status_code, response.text)
                return None
        except Exception as e:
            logger.error("[WEKNORA] datasource_info_error ds_id=%s error=%s", clean_id, e)
            return None

    async def update_datasource_resources(
        self, datasource_id: str, resource_ids: List[str], client: Optional[httpx.AsyncClient] = None, tenant_id: Optional[Union[int, str]] = None
    ) -> bool:
        """
        Cập nhật danh sách resource_ids (folder/doc tokens) cho Data Source.
        Thực hiện GET để bảo toàn các cấu hình khác (sync_schedule, sync_mode...),
        cập nhật config.resource_ids rồi gọi PUT /datasource/{datasource_id}.
        """
        if not self.api_key or not self.base_url or not datasource_id:
            return False

        clean_id = datasource_id.strip()
        current_info = await self.get_datasource_info(clean_id, client=client, tenant_id=tenant_id)
        if not current_info or not isinstance(current_info, dict):
            logger.warning("[WEKNORA] datasource_update_skipped ds_id=%s reason=info_unavailable", clean_id)
            return False

        # Cập nhật danh sách resource_ids
        config = current_info.get("config") or {}
        config["resource_ids"] = list(dict.fromkeys(resource_ids))  # Giữ thứ tự và loại trùng lặp
        current_info["config"] = config

        url = f"{self.base_url}/datasource/{clean_id}"
        headers = dict(self.headers)
        headers["X-Tenant-ID"] = str(tenant_id) if tenant_id else "10000"
        try:
            async with self._get_client_session(client) as http_client:
                response = await http_client.put(url, headers=headers, json=current_info, timeout=30.0)
                if response.status_code == 200:
                    return True
                logger.warning("[WEKNORA] datasource_update_failed ds_id=%s status=%s body=%s", clean_id, response.status_code, response.text)
                return False
        except Exception as e:
            logger.error("[WEKNORA] datasource_update_error ds_id=%s error=%s", clean_id, e)
            return False

    async def trigger_datasource_sync(
        self, datasource_id: str, client: Optional[httpx.AsyncClient] = None, tenant_id: Optional[Union[int, str]] = None
    ) -> Dict[str, Any]:
        """
        Kích hoạt tác vụ đồng bộ ngay lập tức cho Data Source.
        Endpoint: POST /datasource/{datasource_id}/sync
        """
        if not self.api_key or not self.base_url or not datasource_id:
            return {"success": False, "error": "Missing config or datasource_id"}

        clean_id = datasource_id.strip()
        url = f"{self.base_url}/datasource/{clean_id}/sync"
        headers = dict(self.headers)
        headers["X-Tenant-ID"] = str(tenant_id) if tenant_id else "10000"
        try:
            async with self._get_client_session(client) as http_client:
                response = await http_client.post(url, headers=headers, timeout=30.0)
                if response.status_code in (200, 201, 202):
                    return {"success": True, "data": response.json()}
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "error": response.text,
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_datasource_sync_status(self, datasource_id: str, tenant_id: Optional[Union[int, str]] = None) -> Dict[str, Any]:
        """
        Kiểm tra trạng thái đồng bộ và kết quả lần sync gần nhất của Data Source.
        """
        info = await self.get_datasource_info(datasource_id, tenant_id=tenant_id)
        if not info:
            return {"status": "unknown", "error": "Datasource not found"}

        return {
            "id": info.get("id"),
            "name": info.get("name"),
            "status": info.get("status"),
            "last_sync_result": info.get("last_sync_result"),
            "error_message": info.get("error_message"),
            "resource_ids": (info.get("config") or {}).get("resource_ids", []),
            "updated_at": info.get("updated_at"),
        }


weknora_service = WeKnoraService()



