import os
import logging
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

# Загрузка переменных окружения из .env файла
load_dotenv()

# Основные настройки
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
DB_FILE = os.getenv("DB_FILE", "tiktok_queue.db")
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]

# Настройки для проверки TikTok URL
TIKTOK_URL_REGEX = r'https?://(www\.)?(tiktok\.com|vm\.tiktok\.com)/(@[\w\.]+/video/\d+|t/[\w]+)'

# Настройки по умолчанию
DEFAULT_LIKES_REQUIRED = 3
DEFAULT_POINTS_PER_LIKE = 5
DEFAULT_POINTS_PER_SUBMISSION = 10
DEFAULT_LEVEL_THRESHOLD = 50
DEFAULT_SPAM_TIMEOUT = 5  # секунды

# Настройки для Render
PORT = int(os.getenv("PORT", 8080))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "False").lower() == "true"

# Настройки для логирования
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Установка уровня логирования
if LOG_LEVEL == "DEBUG":
    logging.getLogger().setLevel(logging.DEBUG)
elif LOG_LEVEL == "INFO":
    logging.getLogger().setLevel(logging.INFO)
elif LOG_LEVEL == "WARNING":
    logging.getLogger().setLevel(logging.WARNING)
elif LOG_LEVEL == "ERROR":
    logging.getLogger().setLevel(logging.ERROR)
elif LOG_LEVEL == "CRITICAL":
    logging.getLogger().setLevel(logging.CRITICAL)

# Логирование конфигурации при запуске
logging.info("Конфигурация загружена")
logging.info(f"Использование вебхуков: {USE_WEBHOOK}")
logging.info(f"Порт: {PORT}")
logging.info(f"Файл базы данных: {DB_FILE}")
logging.info(f"Количество администраторов: {len(ADMIN_IDS)}")
