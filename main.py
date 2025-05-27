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
    logging.info(f"Устанавливаю вебхук на {WEBHOOK_URL}")
    result = await bot.set_webhook(WEBHOOK_URL)
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
    webhook_path='/',  # Изменено с пустой строки
    on_startup=on_startup_webhook,
    on_shutdown=on_shutdown,
    skip_updates=True,
    host='0.0.0.0',
    port=PORT,
 )

    else:
        # Запуск бота с long polling (для локальной разработки)
        executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
