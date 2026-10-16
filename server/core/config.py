import os
from dotenv import load_dotenv

# Tìm file .env ở thư mục gốc (HiLark)
# config.py nằm ở: HiLark/server/core/config.py
# Nên lùi 3 cấp để về HiLark
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
load_dotenv(dotenv_path=env_path)

class Settings:
    WEKNORA_API_KEY: str = os.getenv("api_weknora", "")
    BASE_URL: str = os.getenv("base_url", "http://localhost/api/v1")
    JEV_API_KEY: str = os.getenv("jev_api", "")
    WEKNORA_DATASET_ID: str = os.getenv("dataset_id", "")
    GEMINI_API_KEY: str = os.getenv("gemini_api", "")
    gemini_api: str = os.getenv("gemini_api", "")

    # MongoDB Settings
    MONGO_URL: str = os.getenv("mongo_url", "mongodb://localhost:27017")
    MONGO_DB: str = os.getenv("mongo_db", "LarkAssistant")
    MONGO_MEMORY_COLLECTION: str = os.getenv("mongo_memory_collection", "memories")
    MONGO_CLAIMS_COLLECTION: str = os.getenv("mongo_claims_collection", "claims")
    MONGO_STAGING_COLLECTION: str = os.getenv("mongo_staging_collection", "conversation_staging")
    MONGO_DIGEST_COLLECTION: str = os.getenv("mongo_digest_collection", "daily_digests")
    MONGO_CHAT_SCOPE_COLLECTION: str = os.getenv("mongo_chat_scope_collection", "chat_scopes")
    MONGO_DRAFT_LOGS_COLLECTION: str = os.getenv("mongo_draft_logs_collection", "draft_logs")

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

    # Lark Base (Bitable) Settings
    LARK_BASE_APP_TOKEN: str = os.getenv("LARK_BASE_APP_TOKEN") or os.getenv("app_token", "")
    LARK_BASE_TABLE_ID: str = os.getenv("LARK_BASE_TABLE_ID") or os.getenv("table_id", "")


    # Daily Digest & Approval Settings
    DIGEST_SCHEDULE_TIME: str = os.getenv("digest_schedule_time", "23:00")
    DIGEST_APPROVER_ID: str = os.getenv("digest_approver_id", "")
    DIGEST_REQUIRE_APPROVAL: bool = os.getenv("digest_require_approval", "true").lower() in ("true", "1")

    # Polling & Real-time Settings
    ENABLE_DM_POLLING: bool = (os.getenv("ENABLE_DM_POLLING") or os.getenv("enable_dm_polling", "false")).lower() in ("true", "1", "yes")
    DM_POLL_INTERVAL: float = float(os.getenv("DM_POLL_INTERVAL") or os.getenv("dm_poll_interval", "60.0"))

    vector_threshold: float = float(os.getenv("vector_threshold") or os.getenv("VECTOR_THRESHOLD", "0.75"))
    keyword_threshold: float = float(os.getenv("keyword_threshold") or os.getenv("KEYWORD_THRESHOLD", "0.75"))

settings = Settings()


