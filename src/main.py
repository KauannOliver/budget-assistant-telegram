import os
import logging
import sys
from dotenv import load_dotenv

from src.sql_client import SQLClient
from src.tools import AgentTools
from src.memory import MemoryManager
from src.skill_loader import SkillLoader
from src.agent_loop import AgentLoop
from src.telegram_handler import TelegramHandler

# Set up logging for tracking operations
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def main():
    print("-----------------------------------")
    print(" CloseClawdio FP&A initialization ")
    print("-----------------------------------")
    
    # Load env vars safely based on .env
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base_dir, ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        print("WARN: No .env file found. Proceeding with system environment variables.")

    # Validation
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token or bot_token == "your_telegram_bot_token_here":
        print("ERROR: TELEGRAM_BOT_TOKEN is missing or invalid in .env")
        sys.exit(1)

    allowed_users_str = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    allowed_users = [u.strip() for u in allowed_users_str.split(",") if u.strip()]
    if not allowed_users:
        print("WARN: TELEGRAM_ALLOWED_USERS is empty. Nobody will be authorized to chat.")

    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key or openai_key == "your_openai_api_key_here":
        print("WARN: OPENAI_API_KEY is not set correctly. The agent loop will likely fail when replying.")

    # Wiring architecture exactly as designed (Modular Monolith)
    sql_client = SQLClient()
    agent_tools = AgentTools(sql_client)
    memory_manager = MemoryManager(db_path=os.path.join(base_dir, "conversations.db"))
    skill_loader = SkillLoader()
    
    agent_loop = AgentLoop(
        tools=agent_tools,
        memory=memory_manager,
        skill_loader=skill_loader
    )
    
    telegram_handler = TelegramHandler(
        token=bot_token,
        allowed_users=allowed_users,
        agent_loop=agent_loop
    )
    
    app = telegram_handler.build_app()
    
    print("Bot is fully wired up. Start polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
