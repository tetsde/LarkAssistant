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

settings = Settings()
