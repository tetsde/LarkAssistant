import json
import logging
import math
import os
from typing import Any, Dict, Optional
from dotenv import load_dotenv

# Tìm file .env ở thư mục gốc (HiLark) hoặc /app/.env
env_candidates = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env'),
    os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'),
    os.path.join(os.getcwd(), '.env'),
    "/.env",
]
for p in env_candidates:
    if os.path.exists(p):
        load_dotenv(dotenv_path=p, override=False)
        break


def _parse_env_float(env_name: str, default: float, *, allow_zero: bool = True) -> float:
    """Đọc số thực không âm từ biến môi trường một cách an toàn khi khởi tạo Settings."""
    raw = os.getenv(env_name)
    if raw is None or not str(raw).strip():
        return default
    try:
        val = float(str(raw).strip())
    except (TypeError, ValueError):
        logging.getLogger("hilark.config").warning(
            "Biến môi trường %s=%r không phải số hợp lệ; sử dụng mặc định %s.",
            env_name,
            raw,
            default,
        )
        return default
    if not math.isfinite(val) or val < 0.0 or (not allow_zero and val == 0.0):
        logging.getLogger("hilark.config").warning(
            "Biến môi trường %s=%r nằm ngoài phạm vi hợp lệ; sử dụng mặc định %s.",
            env_name,
            raw,
            default,
        )
        return default
    return val


def _parse_env_optional_float(env_name: str) -> Optional[float]:
    """Đọc số thực không âm tùy chọn từ env; rỗng/None -> trả về None."""
    raw = os.getenv(env_name)
    if raw is None or not str(raw).strip():
        return None
    try:
        val = float(str(raw).strip())
    except (TypeError, ValueError):
        logging.getLogger("hilark.config").warning(
            "Biến môi trường %s=%r không phải số hợp lệ; sử dụng mặc định None.",
            env_name,
            raw,
        )
        return None
    if not math.isfinite(val) or val < 0.0:
        logging.getLogger("hilark.config").warning(
            "Biến môi trường %s=%r âm hoặc không hữu hạn; sử dụng mặc định None.",
            env_name,
            raw,
        )
        return None
    return val


def _coerce_non_negative_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(val) or val < 0.0:
        return None
    return val


def _normalize_pricing_entry(entry: Any, *, label: str) -> Optional[Dict[str, Any]]:
    """Chuẩn hóa một mục bảng giá (USD / 1M tokens) về dạng {'input', 'output', 'thinking'}."""
    if not isinstance(entry, dict):
        logging.getLogger("hilark.config").warning(
            "Cấu hình giá %s không phải dict hợp lệ; bỏ qua mục này.",
            label,
        )
        return None

    raw_input = entry["input"] if ("input" in entry and entry["input"] is not None) else entry.get("input_per_1m_usd")
    raw_output = entry["output"] if ("output" in entry and entry["output"] is not None) else entry.get("output_per_1m_usd")

    input_val = _coerce_non_negative_float(raw_input)
    output_val = _coerce_non_negative_float(raw_output)
    if input_val is None or output_val is None:
        logging.getLogger("hilark.config").warning(
            "Cấu hình giá %s thiếu hoặc sai định dạng input/output (>= 0); bỏ qua mục này.",
            label,
        )
        return None

    if "thinking" in entry:
        raw_thinking = entry.get("thinking")
    elif "thinking_per_1m_usd" in entry:
        raw_thinking = entry.get("thinking_per_1m_usd")
    else:
        raw_thinking = None

    if raw_thinking is None or (isinstance(raw_thinking, str) and not raw_thinking.strip()):
        thinking_val: Optional[float] = None
    else:
        thinking_val = _coerce_non_negative_float(raw_thinking)
        if thinking_val is None:
            logging.getLogger("hilark.config").warning(
                "Cấu hình giá thinking của %s không hợp lệ (%r); bỏ qua mục này.",
                label,
                raw_thinking,
            )
            return None

    return {
        "input": input_val,
        "output": output_val,
        "thinking": thinking_val,
    }


def _merge_pricing_table(
    baseline: Dict[str, Dict[str, Any]],
    raw_json: str,
    *,
    table_name: str,
) -> Dict[str, Dict[str, Any]]:
    """Gộp bảng giá baseline với JSON override từ cấu hình, an toàn khi JSON sai."""
    merged: Dict[str, Dict[str, Any]] = {
        key.strip().lower(): {
            "input": float(val["input"]),
            "output": float(val["output"]),
            "thinking": float(val["thinking"]) if val.get("thinking") is not None else None,
        }
        for key, val in baseline.items()
    }

    if not raw_json or not str(raw_json).strip():
        return merged

    try:
        parsed = json.loads(raw_json)
    except Exception as exc:
        logging.getLogger("hilark.config").warning(
            "Lỗi parse JSON cho %s (%s); dùng bảng giá baseline.",
            table_name,
            exc,
        )
        return merged

    if not isinstance(parsed, dict):
        logging.getLogger("hilark.config").warning(
            "Cấu hình %s phải là JSON object; dùng bảng giá baseline.",
            table_name,
        )
        return merged

    for raw_key, raw_entry in parsed.items():
        clean_key = str(raw_key or "").strip().lower()
        if not clean_key:
            logging.getLogger("hilark.config").warning(
                "Phát hiện key rỗng trong %s; bỏ qua mục này.",
                table_name,
            )
            continue
        normalized = _normalize_pricing_entry(raw_entry, label=f"{table_name}[{clean_key}]")
        if normalized is not None:
            merged[clean_key] = normalized

    return merged


# Bảng giá mặc định baseline (giá tham khảo USD / 1M tokens)
DEFAULT_LLM_PROVIDER_PRICING_JSON: Dict[str, Dict[str, Any]] = {
    "google": {"input": 0.075, "output": 0.30, "thinking": None},
    "openai": {"input": 0.15, "output": 0.60, "thinking": None},
    "chatgpt": {"input": 0.15, "output": 0.60, "thinking": None},
    "anthropic": {"input": 3.00, "output": 15.00, "thinking": None},
    "custom": {"input": 0.15, "output": 0.60, "thinking": None},
}

DEFAULT_LLM_MODEL_PRICING_JSON: Dict[str, Dict[str, Any]] = {
    # Google Gemini
    "gemini-flash-latest": {"input": 0.075, "output": 0.30, "thinking": None},
    "gemini-3.8-flash": {"input": 0.10, "output": 0.40, "thinking": None},
    "gemini-3.6-flash": {"input": 0.10, "output": 0.40, "thinking": None},
    "gemini-3.5-flash": {"input": 0.10, "output": 0.40, "thinking": None},
    "gemini-3.5-flash-lite": {"input": 0.05, "output": 0.20, "thinking": None},
    "gemini-3.1-pro-preview": {"input": 1.25, "output": 10.0, "thinking": None},
    "gemini-3.1-flash-lite": {"input": 0.05, "output": 0.20, "thinking": None},
    "gemini-3-flash": {"input": 0.10, "output": 0.40, "thinking": None},
    "gemini-3-pro-preview": {"input": 1.25, "output": 10.0, "thinking": None},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0, "thinking": None},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60, "thinking": None},
    "gemini-2.5-flash-lite": {"input": 0.075, "output": 0.30, "thinking": None},
    # OpenAI
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "thinking": None},
    "gpt-4o": {"input": 2.50, "output": 10.0, "thinking": None},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0, "thinking": None},
    "o3-mini": {"input": 1.10, "output": 4.40, "thinking": None},
    "o1": {"input": 15.0, "output": 60.0, "thinking": None},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50, "thinking": None},
    # Anthropic
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00, "thinking": None},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00, "thinking": None},
    "claude-3-7-sonnet": {"input": 3.00, "output": 15.00, "thinking": None},
}

class Settings:
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    SETUP_REQUIRE_DURABLE_STATE: bool = (
        os.getenv("SETUP_REQUIRE_DURABLE_STATE", "")
        or ("true" if ENVIRONMENT.lower() == "production" else "false")
    ).lower() in ("true", "1", "yes")
    WEKNORA_API_KEY: str = os.getenv("WEKNORA_API_KEY") or os.getenv("api_weknora", "")
    BASE_URL: str = os.getenv("BASE_URL") or os.getenv("base_url", "http://localhost/api/v1")
    JEV_API_KEY: str = os.getenv("JEV_API_KEY") or os.getenv("jev_api", "")
    WEKNORA_DATASET_ID: str = os.getenv("WEKNORA_DATASET_ID") or os.getenv("dataset_id", "")
    WEKNORA_WIKI_DATASET_ID: str = os.getenv("wiki_dataset_id") or os.getenv("WEKNORA_WIKI_DATASET_ID", "")
    # Ba giá trị dưới đây TỪNG có default hardcode thuộc về MỘT doanh nghiệp cụ thể.
    # Default đã bị xoá theo GĐ2 của kế hoạch "Tenant Resolution & Token Fix": thiếu là chuỗi rỗng,
    # và chuỗi rỗng nghĩa là "chưa cấu hình cho tenant này", không phải "dùng kho của công ty khác".
    # Nguồn đúng: collection `tenants` (weknora_policy_dataset_id, weknora_wiki_dataset_id,
    # weknora_policy_datasource_id, company_policy_table_id) qua `services.tenancy.tenant_resolver`.
    WEKNORA_POLICY_DATASET_ID: str = os.getenv("policy_dataset_id") or os.getenv("WEKNORA_POLICY_DATASET_ID", "")
    WEKNORA_POLICY_DATASOURCE_ID: str = os.getenv("policy_datasource_id") or os.getenv("WEKNORA_POLICY_DATASOURCE_ID", "")
    WEKNORA_WEB_URL: str = os.getenv("WEKNORA_WEB_URL") or "http://localhost/login"
    WEKNORA_PROVISION_DRY_RUN: bool = (os.getenv("WEKNORA_PROVISION_DRY_RUN", "false").lower() in ("true", "1", "yes"))
    POLICY_SYNC_ENABLED: bool = (os.getenv("policy_sync_enabled") or os.getenv("POLICY_SYNC_ENABLED", "true")).lower() in ("true", "1", "yes")
    POLICY_SYNC_INTERVAL_SECONDS: int = int(os.getenv("policy_sync_interval_seconds") or os.getenv("POLICY_SYNC_INTERVAL_SECONDS", "3600"))
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY") or os.getenv("gemini_api", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Backward compatibility alias
    @property
    def gemini_api(self) -> str:
        return self.GEMINI_API_KEY

    # MongoDB Settings
    MONGO_URL: str = os.getenv("MONGO_URL") or os.getenv("mongo_url") or os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    MONGO_DB: str = os.getenv("MONGO_DB") or os.getenv("mongo_db", "LarkAssistant")
    MONGO_MEMORY_COLLECTION: str = os.getenv("mongo_memory_collection", "memories")
    MONGO_CLAIMS_COLLECTION: str = os.getenv("mongo_claims_collection", "claims")
    MONGO_STAGING_COLLECTION: str = os.getenv("mongo_staging_collection", "conversation_staging")
    MONGO_DIGEST_COLLECTION: str = os.getenv("mongo_digest_collection", "daily_digests")
    MONGO_CHAT_SCOPE_COLLECTION: str = os.getenv("mongo_chat_scope_collection", "chat_scopes")
    MONGO_DRAFT_LOGS_COLLECTION: str = os.getenv("mongo_draft_logs_collection", "draft_logs")
    MONGO_MASTER_DIGEST_COLLECTION: str = os.getenv("mongo_master_digest_collection", "master_daily_digests")
    MONGO_AUTH_COLLECTION: str = os.getenv("mongo_auth_collection", "lark_auth")
    # state OAuth do server phát hành (GĐ4): {_id: state, tenant_key, app_id, purpose}
    MONGO_OAUTH_STATES_COLLECTION: str = os.getenv("mongo_oauth_states_collection", "oauth_states")
    MONGO_TELEMETRY_COLLECTION: str = os.getenv("mongo_telemetry_collection", "cost_telemetry")
    MONGO_USER_SETTINGS_COLLECTION: str = os.getenv("mongo_user_settings_collection", "user_settings")
    MONGO_SYSTEM_CONFIG_COLLECTION: str = os.getenv("mongo_system_config_collection", "system_config")
    MONGO_SETUP_SESSIONS_COLLECTION: str = os.getenv("mongo_setup_sessions_collection", "setup_sessions")
    MONGO_LARK_APPS_COLLECTION: str = os.getenv("mongo_lark_apps_collection", "lark_app_credentials")
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000")
    LARK_OAUTH_REDIRECT_URI: str = os.getenv("lark_oauth_redirect_uri", "")
    ENCRYPTION_SECRET_KEY: str = os.getenv("ENCRYPTION_SECRET_KEY", "hilark-secret-key-32bytes-aes256!!")

    # Lark Settings
    LARK_APP_ID: str = os.getenv("app_id") or os.getenv("LARK_APP_ID", "")
    LARK_APP_SECRET: str = os.getenv("app_secret") or os.getenv("LARK_APP_SECRET", "")
    LARK_VERIFICATION_TOKEN: str = os.getenv("verification_token") or os.getenv("LARK_VERIFICATION_TOKEN", "")
    LARK_ENCRYPT_KEY: str = os.getenv("encrypt_key") or os.getenv("LARK_ENCRYPT_KEY", "")
    LARK_DOMAIN: str = os.getenv("lark_domain") or os.getenv("LARK_DOMAIN", "https://open.larksuite.com")
    LARK_USER_ACCESS_TOKEN: str = os.getenv("access_token_user") or os.getenv("LARK_USER_ACCESS_TOKEN", "")
    LARK_USER_OPEN_ID: str = os.getenv("user_open_id") or os.getenv("LARK_USER_OPEN_ID", "")
    LARK_USER_NAME: str = os.getenv("user_name") or os.getenv("LARK_USER_NAME", "")
    LARK_USER_ROLE: str = os.getenv("user_role") or os.getenv("LARK_USER_ROLE", "")

    # Lark ISV / Store App Multi-Tenant Settings (EDL-0020)
    LARK_APP_TYPE: str = os.getenv("LARK_APP_TYPE", "custom")
    IS_ISV_MODE: bool = (os.getenv("LARK_APP_TYPE", "").lower() == "isv") or (os.getenv("IS_ISV_MODE", "false").lower() in ("true", "1", "yes"))
    LARK_APP_TICKET: str = os.getenv("LARK_APP_TICKET", "")
    MONGO_ISV_AUTH_COLLECTION: str = os.getenv("mongo_isv_auth_collection", "isv_auth")
    MONGO_TENANTS_COLLECTION: str = os.getenv("mongo_tenants_collection", "tenants")

    # Lark Base (Bitable) Settings
    LARK_BASE_APP_TOKEN: str = os.getenv("LARK_BASE_APP_TOKEN") or os.getenv("app_token", "")
    LARK_BASE_TABLE_ID: str = os.getenv("LARK_BASE_TABLE_ID") or os.getenv("table_id", "")
    LARK_BASE_POLICY_TABLE_ID: str = os.getenv("policy_table_id") or os.getenv("LARK_BASE_POLICY_TABLE_ID", "")

    # Daily Digest & Approval Settings
    DIGEST_SCHEDULE_TIME: str = os.getenv("digest_schedule_time", "23:00")
    DIGEST_APPROVER_ID: str = os.getenv("digest_approver_id", "")
    DIGEST_REQUIRE_APPROVAL: bool = os.getenv("digest_require_approval", "true").lower() in ("true", "1")

    # RAG Search Thresholds
    vector_threshold: float = float(os.getenv("vector_threshold") or os.getenv("VECTOR_THRESHOLD", "0.75"))
    keyword_threshold: float = float(os.getenv("keyword_threshold") or os.getenv("KEYWORD_THRESHOLD", "0.75"))

    @property
    def VECTOR_THRESHOLD(self) -> float:
        return self.vector_threshold

    @property
    def KEYWORD_THRESHOLD(self) -> float:
        return self.keyword_threshold

    # Rate Limiting, Message Debounce & Concurrency
    DEBOUNCE_DELAY_SECONDS: float = float(os.getenv("DEBOUNCE_DELAY_SECONDS", "1.75"))
    USER_COOLDOWN_SECONDS: float = float(os.getenv("USER_COOLDOWN_SECONDS", "4.0"))
    MAX_CONCURRENT_CHAT_PIPELINES: int = int(os.getenv("MAX_CONCURRENT_CHAT_PIPELINES", "3"))
    CHAT_QUEUE_MAX_SIZE: int = int(os.getenv("CHAT_QUEUE_MAX_SIZE", "100"))
    CHAT_QUEUE_ENQUEUE_TIMEOUT: float = float(os.getenv("CHAT_QUEUE_ENQUEUE_TIMEOUT", "2.0"))

    # WeKnora DocReader gRPC Settings (EDL-0010)
    DOCREADER_GRPC_HOST: str = os.getenv("DOCREADER_GRPC_HOST", "127.0.0.1")
    DOCREADER_GRPC_PORT: int = int(os.getenv("DOCREADER_GRPC_PORT", "50051"))
    DOCREADER_TIMEOUT_SECONDS: int = int(os.getenv("DOCREADER_TIMEOUT_SECONDS", "60"))

    # Cost Telemetry & Multi-Provider Pricing Settings
    USD_TO_VND_RATE: float = _parse_env_float("USD_TO_VND_RATE", 25400.0, allow_zero=False)
    JEV_FLAT_COST_PER_REQUEST: float = _parse_env_float("JEV_FLAT_COST_PER_REQUEST", 0.0001)
    LLM_DEFAULT_INPUT_COST_PER_1M_USD: float = _parse_env_float("LLM_DEFAULT_INPUT_COST_PER_1M_USD", 0.075)
    LLM_DEFAULT_OUTPUT_COST_PER_1M_USD: float = _parse_env_float("LLM_DEFAULT_OUTPUT_COST_PER_1M_USD", 0.30)
    LLM_DEFAULT_THINKING_COST_PER_1M_USD: Optional[float] = _parse_env_optional_float("LLM_DEFAULT_THINKING_COST_PER_1M_USD")
    LLM_PROVIDER_DEFAULT_PRICING_JSON: str = os.getenv("LLM_PROVIDER_DEFAULT_PRICING_JSON", "")
    LLM_MODEL_PRICING_JSON: str = os.getenv("LLM_MODEL_PRICING_JSON", "")

    def __init__(self) -> None:
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
        self.USD_TO_VND_RATE = _parse_env_float("USD_TO_VND_RATE", 25400.0, allow_zero=False)
        self.JEV_FLAT_COST_PER_REQUEST = _parse_env_float("JEV_FLAT_COST_PER_REQUEST", 0.0001)
        self.LLM_DEFAULT_INPUT_COST_PER_1M_USD = _parse_env_float("LLM_DEFAULT_INPUT_COST_PER_1M_USD", 0.075)
        self.LLM_DEFAULT_OUTPUT_COST_PER_1M_USD = _parse_env_float("LLM_DEFAULT_OUTPUT_COST_PER_1M_USD", 0.30)
        self.LLM_DEFAULT_THINKING_COST_PER_1M_USD = _parse_env_optional_float("LLM_DEFAULT_THINKING_COST_PER_1M_USD")
        self.LLM_PROVIDER_DEFAULT_PRICING_JSON = os.getenv("LLM_PROVIDER_DEFAULT_PRICING_JSON", "")
        self.LLM_MODEL_PRICING_JSON = os.getenv("LLM_MODEL_PRICING_JSON", "")
        self._init_provider_pricing_json = self.LLM_PROVIDER_DEFAULT_PRICING_JSON
        self._init_model_pricing_json = self.LLM_MODEL_PRICING_JSON

    def _resolve_json_override(self, attr_name: str, init_attr_name: str, env_name: str) -> str:
        attr_val = getattr(self, attr_name, "")
        init_val = getattr(self, init_attr_name, "")
        if attr_val != init_val:
            return attr_val if isinstance(attr_val, str) else ""
        env_val = os.getenv(env_name)
        if env_val is not None:
            return env_val
        return attr_val if isinstance(attr_val, str) else ""

    def get_provider_default_pricing(self) -> Dict[str, Dict[str, Any]]:
        """Trả về bảng giá mặc định theo từng provider (USD / 1M tokens) sau khi gộp override JSON."""
        raw_json = self._resolve_json_override(
            "LLM_PROVIDER_DEFAULT_PRICING_JSON",
            "_init_provider_pricing_json",
            "LLM_PROVIDER_DEFAULT_PRICING_JSON",
        )
        return _merge_pricing_table(
            DEFAULT_LLM_PROVIDER_PRICING_JSON,
            raw_json,
            table_name="LLM_PROVIDER_DEFAULT_PRICING_JSON",
        )

    def get_model_pricing_table(self) -> Dict[str, Dict[str, Any]]:
        """Trả về bảng giá theo từng model (USD / 1M tokens) sau khi gộp override JSON."""
        raw_json = self._resolve_json_override(
            "LLM_MODEL_PRICING_JSON",
            "_init_model_pricing_json",
            "LLM_MODEL_PRICING_JSON",
        )
        return _merge_pricing_table(
            DEFAULT_LLM_MODEL_PRICING_JSON,
            raw_json,
            table_name="LLM_MODEL_PRICING_JSON",
        )

settings = Settings()


