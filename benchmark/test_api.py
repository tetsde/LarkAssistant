import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.config import load_config
from benchmark.llm_client import LLMClient, EmbeddingClient

def test_api():
    print("Loading config...")
    config = load_config(PROJECT_ROOT / ".env")
    
    print(f"LLM Base URL: {config.llm.base_url}")
    print(f"LLM Model: {config.llm.model}")
    print(f"Embedding Model: {config.embedding.model}")
    
    print("\nTesting Chat Completion (Gemini 1.5 Flash)...")
    llm = LLMClient(config.llm, config.pricing)
    try:
        reply, tokens, elapsed = llm.chat([{"role": "user", "content": "Hello, who are you?"}])
        print(f"Response: {reply.strip()}")
        print(f"Tokens: {tokens}")
        print(f"Time: {elapsed:.2f}s")
        print("✅ Chat Completion API is working!")
    except Exception as e:
        print(f"❌ Chat Completion API failed: {e}")

    print("\nTesting Embeddings (text-embedding-004)...")
    embedder = EmbeddingClient(config.embedding, config.pricing)
    try:
        emb, tokens = embedder.embed_single("Test sentence for embedding.")
        print(f"Embedding length: {len(emb)}")
        print(f"Tokens: {tokens}")
        print("✅ Embeddings API is working!")
    except Exception as e:
        print(f"❌ Embeddings API failed: {e}")

if __name__ == "__main__":
    test_api()
