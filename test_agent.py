import asyncio
from backend.core.agents.coordinator import MasterCoordinator
import os

os.environ["LLM_MODEL_NAME"] = "test"

async def main():
    print("Initializing Master Coordinator...")
    coordinator = MasterCoordinator(model_name="test", qdrant_url="http://localhost:6333")
    print("Success: Coordinator instantiated.")

if __name__ == "__main__":
    asyncio.run(main())
