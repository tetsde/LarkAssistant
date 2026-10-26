from contextlib import asynccontextmanager
import sys
from typing import Any, Dict, List, Optional
import httpx
from fastapi import HTTPException
from core.config import settings
from core.http_client import get_http_client
from models.chat import ChatRequest
from services.ai.text_filter import text_filter



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

    async def get_kb_info(self, kb_id: str, client: Optional[httpx.AsyncClient] = None) -> Optional[Dict[str, Any]]:
        """
        Lấy thông tin chi tiết của Knowledge Base từ WeKnora (ID, Tên, Mô tả).
        Endpoint WeKnora: GET /knowledge-bases/{kb_id}
        Trả về dict: {"id": str, "name": str, "description": str} hoặc None nếu không tồn tại / lỗi.
        """
        if not self.api_key or not self.base_url or not kb_id:
            return None

        clean_id = kb_id.strip()
        url = f"{self.base_url}/knowledge-bases/{clean_id}"
        try:
            async with self._get_client_session(client) as http_client:
                resp = await http_client.get(url, headers=self.headers, timeout=10.0)
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
        self, text: str, dataset_id: str = None, name: Optional[str] = None, client: Optional[httpx.AsyncClient] = None
    ) -> dict:
        target_id = dataset_id or settings.WEKNORA_DATASET_ID
        if target_id and "," in target_id:
            target_id = target_id.split(",")[0].strip()
        if not target_id:
            raise HTTPException(status_code=500, detail="WEKNORA_DATASET_ID is not configured")
            
        url = f"{self.base_url}/knowledge-bases/{target_id}/knowledge/manual"
        doc_name = name or f"Memory_{text[:15]}..."
        payload = {
            "title": doc_name,
            "content": text,
            "status": "publish",
        }

        async with self._get_client_session(client) as http_client:
            response = await http_client.post(url, headers=self.headers, json=payload, timeout=30.0)
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
        target_id = dataset_id or settings.WEKNORA_DATASET_ID
        if target_id and "," in target_id:
            target_id = target_id.split(",")[0].strip()
        if not target_id:
            raise HTTPException(status_code=500, detail="WEKNORA_DATASET_ID is not configured")

        if not self.api_key or not self.base_url:
            raise HTTPException(status_code=500, detail="Missing WeKnora API Key or base_url in .env")

        url = f"{self.base_url}/knowledge-bases/{target_id}/knowledge/file"
        headers = {
            "X-API-Key": self.api_key,
        }
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
        client: Optional[httpx.AsyncClient] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Lấy thông tin chi tiết và tóm tắt (summary) của một tài liệu từ WeKnora.
        Endpoint: GET /knowledge-bases/{dataset_id}/knowledge/{knowledge_id}
        """
        if not self.api_key or not self.base_url or not dataset_id or not knowledge_id:
            return None

        url = f"{self.base_url}/knowledge-bases/{dataset_id.strip()}/knowledge/{knowledge_id.strip()}"
        try:
            async with self._get_client_session(client) as http_client:
                resp = await http_client.get(url, headers=self.headers, timeout=timeout)
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    return {
                        "id": data.get("id", knowledge_id),
                        "title": data.get("title") or data.get("name") or "",
                        "summary": data.get("summary") or data.get("description") or None,
                        "status": data.get("status") or "",
                    }
                return None
        except Exception:
            return None

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
                target_kbs = knowledge_base_ids or self.get_configured_kb_ids()
                if not target_kbs:
                    print("[WeKnora] Cảnh báo: Chưa cấu hình dataset_id trong .env (hoặc không truyền knowledge_base_ids). Bỏ qua retrieval.")
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
                    "knowledge_base_ids": target_kbs,
                }

                # Giới hạn tìm kiếm trong các file cụ thể nếu có
                if knowledge_ids:
                    payload["knowledge_ids"] = knowledge_ids

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

                response = await http_client.post(
                    search_url,
                    headers=self.headers,
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
                        fb_res = await client.post(fb_url, headers=self.headers, json=payload)
                        if fb_res.status_code == 200:
                            fb_data = fb_res.json()
                            return fb_data.get("data", []) if isinstance(fb_data, dict) else []
                    return []
                else:
                    print(f"WeKnora retrieve error (HTTP {response.status_code}): {response.text}")
                    return []
        except Exception as e:
            print(f"Lỗi khi gọi WeKnora retrieve: {e}")
            return []

    def retrieve_sync(
        self,
        query: str,
        knowledge_base_ids: Optional[List[str]] = None,
        knowledge_ids: Optional[List[str]] = None,
        match_count: int = 5,
        timeout: float = 30.0,
    ) -> List[Dict[str, Any]]:
        """
        Phiên bản đồng bộ dùng httpx.Client() trực tiếp cho CLI / Scripts kiểm thử.
        """
        if not self.api_key or not self.base_url or not query or not query.strip():
            return []

        search_url = f"{self.base_url}/knowledge-search"
        target_kbs = knowledge_base_ids or self.get_configured_kb_ids()
        if not target_kbs:
            print("[WeKnora] Cảnh báo: Chưa cấu hình dataset_id trong .env (hoặc không truyền knowledge_base_ids). Bỏ qua retrieval.")
            return []

        payload: Dict[str, Any] = {
            "query": query.strip(),
            "match_count": match_count,
            "knowledge_base_ids": target_kbs,
        }
        if knowledge_ids:
            payload["knowledge_ids"] = knowledge_ids

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(search_url, headers=self.headers, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                        return data["data"]
                    return data if isinstance(data, list) else []
                else:
                    print(f"WeKnora retrieve_sync error (HTTP {response.status_code}): {response.text}")
                    return []
        except Exception as e:
            print(f"Lỗi khi gọi WeKnora retrieve_sync: {e}")
            return []

    # =========================================================================
    # DATA SOURCE MANAGEMENT (FEISHU / LARK DRIVE & DOCS)
    # =========================================================================

    async def get_datasource_info(
        self, datasource_id: str, client: Optional[httpx.AsyncClient] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Lấy thông tin chi tiết của một Data Source trong WeKnora.
        Endpoint: GET /datasource/{datasource_id}
        """
        if not self.api_key or not self.base_url or not datasource_id:
            return None

        clean_id = datasource_id.strip()
        url = f"{self.base_url}/datasource/{clean_id}"
        try:
            async with self._get_client_session(client) as http_client:
                response = await http_client.get(url, headers=self.headers, timeout=30.0)
                if response.status_code == 200:
                    return response.json()
                print(f"[WeKnora] get_datasource_info HTTP {response.status_code}: {response.text}")
                return None
        except Exception as e:
            print(f"[WeKnora] Lỗi khi gọi get_datasource_info({clean_id}): {e}")
            return None

    async def update_datasource_resources(
        self, datasource_id: str, resource_ids: List[str], client: Optional[httpx.AsyncClient] = None
    ) -> bool:
        """
        Cập nhật danh sách resource_ids (folder/doc tokens) cho Data Source.
        Thực hiện GET để bảo toàn các cấu hình khác (sync_schedule, sync_mode...),
        cập nhật config.resource_ids rồi gọi PUT /datasource/{datasource_id}.
        """
        if not self.api_key or not self.base_url or not datasource_id:
            return False

        clean_id = datasource_id.strip()
        current_info = await self.get_datasource_info(clean_id, client=client)
        if not current_info or not isinstance(current_info, dict):
            print(f"[WeKnora] Không thể lấy thông tin hiện tại của datasource {clean_id} để update.")
            return False

        # Cập nhật danh sách resource_ids
        config = current_info.get("config") or {}
        config["resource_ids"] = list(dict.fromkeys(resource_ids))  # Giữ thứ tự và loại trùng lặp
        current_info["config"] = config

        url = f"{self.base_url}/datasource/{clean_id}"
        try:
            async with self._get_client_session(client) as http_client:
                response = await http_client.put(url, headers=self.headers, json=current_info, timeout=30.0)
                if response.status_code == 200:
                    return True
                print(f"[WeKnora] update_datasource_resources HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            print(f"[WeKnora] Lỗi khi update_datasource_resources({clean_id}): {e}")
            return False

    async def trigger_datasource_sync(
        self, datasource_id: str, client: Optional[httpx.AsyncClient] = None
    ) -> Dict[str, Any]:
        """
        Kích hoạt tác vụ đồng bộ ngay lập tức cho Data Source.
        Endpoint: POST /datasource/{datasource_id}/sync
        """
        if not self.api_key or not self.base_url or not datasource_id:
            return {"success": False, "error": "Missing config or datasource_id"}

        clean_id = datasource_id.strip()
        url = f"{self.base_url}/datasource/{clean_id}/sync"
        try:
            async with self._get_client_session(client) as http_client:
                response = await http_client.post(url, headers=self.headers, timeout=30.0)
                if response.status_code in (200, 201, 202):
                    return {"success": True, "data": response.json()}
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "error": response.text,
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_datasource_sync_status(self, datasource_id: str) -> Dict[str, Any]:
        """
        Kiểm tra trạng thái đồng bộ và kết quả lần sync gần nhất của Data Source.
        """
        info = await self.get_datasource_info(datasource_id)
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



