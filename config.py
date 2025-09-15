import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BOT_PREFIX = "$"

# Все настройки ролей и каналов удалены.
# Доступ к командам реализуется через @commands.has_permissions(administrator=True) или @commands.has_role("Staff") в самих командах.

ATTACK_ALERT_CHANNEL_ID = None  # Оставлено для примера, если понадобится канал для алертов