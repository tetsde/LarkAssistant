from pydantic import BaseModel
import os
import re
import json
import uuid
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Any, Optional, List, Union, Dict, Tuple
import httpx
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    query: str
    agent_enabled: bool = True
    agent_id: str = "builtin-quick-answer" # Hoặc "builtin-quick-answer"
    channel: str = "api"


