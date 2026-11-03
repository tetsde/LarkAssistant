import os
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

    # Polling & Real-time Settings
    ENABLE_LARK_WEBSOCKET: bool = (os.getenv("ENABLE_LARK_WEBSOCKET") or os.getenv("enable_lark_websocket", "false")).lower() in ("true", "1", "yes")
    ENABLE_DM_POLLING: bool = (os.getenv("ENABLE_DM_POLLING") or os.getenv("enable_dm_polling", "false")).lower() in ("true", "1", "yes")
    DM_POLL_INTERVAL: float = float(os.getenv("DM_POLL_INTERVAL") or os.getenv("dm_poll_interval", "60.0"))

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

settings = Settings()


