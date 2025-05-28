import logging
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.webhook import SendMessage
from aiogram.utils.executor import start_webhook

from bot import dp, bot, on_startup
from config import PORT, WEBHOOK_URL, USE_WEBHOOK

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация хранилища состояний
storage = MemoryStorage()

# Настройка вебхуков для Render
async def on_startup_webhook(dp):
    await on_startup(dp)
    # Сначала удаляем текущий вебхук
    await bot.delete_webhook()
    logging.info(f"Устанавливаю вебхук на {https://tiktok-like-bot.onrender.com}")
    result = await bot.set_webhook(https://tiktok-like-bot.onrender.com)
    logging.info(f"Результат установки вебхука: {result}")

async def on_shutdown(dp):
    logging.warning('Shutting down..')
    await bot.delete_webhook()
    await dp.storage.close()
    await dp.storage.wait_closed()
    logging.warning('Bye!')

if __name__ == '__main__':
    if USE_WEBHOOK:
        # Запуск бота с вебхуками (для Render)
        start_webhook(
            dispatcher=dp,
            webhook_path='',
            on_startup=on_startup_webhook,
            on_shutdown=on_shutdown,
            skip_updates=True,
            host='0.0.0.0',
            port=PORT,
        )
    else:
        # Запуск бота с long polling (для локальной разработки)
        executor.start_polling(dp, on_startup=on_startup, skip_updates=True)

# добавлено 29 мая временно
async def on_startup(dp):
    """Actions to perform on startup"""
    logging.info("Starting bot...")
    
    # Добавляем тестовые данные при каждом запуске
    conn = db.connect()
    cursor = conn.cursor()
    
    # Проверяем, есть ли видео в базе
    cursor.execute("SELECT COUNT(*) as count FROM videos")
    videos_count = cursor.fetchone()['count']
    
    # Если видео нет, добавляем тестовые
    if videos_count == 0:
        logging.info("Добавляю тестовые видео в базу")
        # Добавляем админа как пользователя, если его нет
        admin_id = ADMIN_IDS[0] if ADMIN_IDS else 123456789
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, joined_date, last_action, is_admin) VALUES (?, ?, ?, datetime('now'), datetime('now'), 1)",
            (admin_id, "admin", "Admin")
        )
        
        # Добавляем тестовые видео
        test_videos = [
            "https://www.tiktok.com/@example1/video/1234567890",
            "https://www.tiktok.com/@example2/video/0987654321",
            "https://www.tiktok.com/@example3/video/5678901234"
        ]
        
        for video in test_videos:
            cursor.execute(
                "INSERT INTO videos (user_id, tiktok_url, submission_time ) VALUES (?, ?, datetime('now'))",
                (admin_id, video)
            )
        
        conn.commit()
        logging.info(f"Добавлено {len(test_videos)} тестовых видео")
    
    conn.close()
    
    # Установка команд бота
    await dp.bot.set_my_commands([
        # ваши команды
    ])

