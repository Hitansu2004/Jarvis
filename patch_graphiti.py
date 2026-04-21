import re

with open("memory_vault/graphiti_store.py", "r") as f:
    content = f.read()

new_init = """        try:
            from graphiti_core import Graphiti
            from graphiti_core.driver.kuzu_driver import KuzuDriver
            from graphiti_core.llm_client.openai_client import OpenAIClient
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
            import os

            ollama_url = os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/v1"
            llm_model = os.getenv("MODEL_ORCHESTRATOR", "gemma4:e4b")
            embed_model = os.getenv("GRAPHITI_EMBEDDING_MODEL", "nomic-embed-text")

            llm_config = LLMConfig(api_key="ollama", base_url=ollama_url, model=llm_model)
            llm_client = OpenAIClient(config=llm_config)

            embedder_config = OpenAIEmbedderConfig(api_key="ollama", base_url=ollama_url, embedding_model=embed_model)
            embedder = OpenAIEmbedder(config=embedder_config)

            driver = KuzuDriver(str(self._db_path))
            self._client = Graphiti(graph_driver=driver, llm_client=llm_client, embedder=embedder)
            await self._client.build_indices_and_constraints()"""

content = re.sub(
    r"        try:\n            from graphiti_core import Graphiti.*?await self._client\.build_indices_and_constraints\(\)",
    new_init,
    content,
    flags=re.DOTALL
)

with open("memory_vault/graphiti_store.py", "w") as f:
    f.write(content)

