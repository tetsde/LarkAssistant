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

    # Lark Settings
    LARK_APP_ID: str = os.getenv("app_id") or os.getenv("LARK_APP_ID", "")
    LARK_APP_SECRET: str = os.getenv("app_secret") or os.getenv("LARK_APP_SECRET", "")
    LARK_VERIFICATION_TOKEN: str = os.getenv("verification_token") or os.getenv("LARK_VERIFICATION_TOKEN", "")
    LARK_ENCRYPT_KEY: str = os.getenv("encrypt_key") or os.getenv("LARK_ENCRYPT_KEY", "")
    LARK_DOMAIN: str = os.getenv("lark_domain") or os.getenv("LARK_DOMAIN", "https://open.larksuite.com")
    LARK_USER_ACCESS_TOKEN: str = os.getenv("access_token_user") or os.getenv("LARK_USER_ACCESS_TOKEN", "")

settings = Settings()

