import re
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.utils.exceptions import TelegramAPIError

from database import Database
from config import BOT_TOKEN, DB_FILE, ADMIN_IDS, TIKTOK_URL_REGEX

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# Initialize database
db = Database(DB_FILE)

# Define states for conversation
class BotStates(StatesGroup):
    waiting_for_url = State()
    waiting_for_like_confirmation = State()
    waiting_for_admin_action = State()
    waiting_for_admin_user_id = State()
    waiting_for_admin_points = State()
    waiting_for_admin_level = State()


# Helper functions
def is_valid_tiktok_url(url):
    """Check if the URL is a valid TikTok URL"""
    return bool(re.match(TIKTOK_URL_REGEX, url))


def get_user_mention(user):
    """Get a mention for a user"""
    if user.username:
        return f"@{user.username}"
    else:
        return f"[{user.first_name}](tg://user?id={user.id})"


async def check_spam(message: types.Message, command: str):
    """Check if a user is spamming commands"""
    user_id = message.from_user.id
    
    # Admins bypass spam protection
    if user_id in ADMIN_IDS or db.is_admin(user_id):
        return False
    
    if not db.can_execute_command(user_id, command):
        await message.reply("Пожалуйста, не отправляйте команды слишком часто.")
        return True
    
    db.record_command(user_id, command)
    return False


# Command handlers
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    """Handle /start command"""
    logging.info(f"Получена команда /start от пользователя {message.from_user.id}")
    # остальной код функции
    if await check_spam(message, 'start'):
        return
    
    user = message.from_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    db.update_user_last_action(user.id)
    
    # Set admin status if user ID is in ADMIN_IDS
    if user.id in ADMIN_IDS and not db.is_admin(user.id):
        db.set_admin_status(user.id, True)
    
    welcome_text = (
        f"👋 Привет, {get_user_mention(user)}!\n\n"
        f"Я бот для управления очередью TikTok-видео. Вот что я умею:\n\n"
        f"📌 /submit [ссылка] - отправить видео в очередь\n"
        f"👍 /like [номер] - подтвердить, что вы лайкнули видео\n"
        f"📋 /queue - показать текущую очередь видео\n"
        f"📊 /status - показать вашу статистику\n\n"
        f"Чтобы добавить своё видео, вам нужно сначала лайкнуть {db.get_likes_required()} видео из очереди."
    )
    
    await message.reply(welcome_text, parse_mode=ParseMode.MARKDOWN)


@dp.message_handler(commands=['submit'])
async def cmd_submit(message: types.Message):
    """Handle /submit command"""
    logging.info(f"Получена команда /submit от пользователя {message.from_user.id}")
    if await check_spam(message, 'submit'):
        return
    
    user_id = message.from_user.id
    db.update_user_last_action(user_id)
    
    # Check if user can submit a video
    if not db.can_submit_video(user_id):
        likes_given = db.get_user(user_id)['likes_given']
        likes_required = db.get_likes_required()
        likes_needed = likes_required - likes_given
        
        await message.reply(
            f"Вы не можете добавить видео, пока не лайкнете еще {likes_needed} видео из очереди.\n"
            f"Используйте /queue для просмотра очереди и /like [номер] для подтверждения лайка."
        )
        return
    
    # Check if URL was provided with command
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) > 1:
        url = command_parts[1].strip()
        if is_valid_tiktok_url(url):
            video_id = db.add_video(user_id, url)
            leveled_up = db.increment_user_submissions(user_id)
            
            response = f"✅ Ваше видео успешно добавлено в очередь под номером {video_id}!\n" \
                      f"Используйте /queue для просмотра очереди."
            
            if leveled_up:
                user_data = db.get_user(user_id)
                response += f"\n🎉 Поздравляем! Вы достигли уровня {user_data['level']}!"
                
                # Add bonus for level up
                if user_data['level'] > 1:
                    bonus_points = user_data['level'] * 10
                    conn = db.connect()
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE users SET points = points + ? WHERE user_id = ?",
                        (bonus_points, user_id)
                    )
                    conn.commit()
                    conn.close()
                    
                    response += f"\n💰 Бонус за новый уровень: +{bonus_points} очков!"
            
            await message.reply(response)
        else:
            await message.reply(
                "❌ Неверная ссылка на TikTok. Пожалуйста, убедитесь, что вы отправляете корректную ссылку на видео."
            )
    else:
        await message.reply(
            "Пожалуйста, укажите ссылку на TikTok видео после команды.\n"
            "Пример: /submit https://www.tiktok.com/@username/video/1234567890"
        )


@dp.message_handler(commands=['like'])
async def cmd_like(message: types.Message):
    """Handle /like command"""
    if await check_spam(message, 'like'):
        return
    
    user_id = message.from_user.id
    db.update_user_last_action(user_id)
    
    # Check if video ID was provided with command
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) > 1:
        try:
            video_id = int(command_parts[1].strip())
            video = db.get_video(video_id)
            
            if not video:
                await message.reply(f"❌ Видео с номером {video_id} не найдено в очереди.")
                return
            
            # Check if user is trying to like their own video
            if video['user_id'] == user_id:
                await message.reply("❌ Вы не можете лайкать свои собственные видео.")
                return
            
            # Check if user has already liked this video
            if db.has_liked_video(user_id, video_id):
                await message.reply(f"❌ Вы уже лайкнули видео #{video_id}.")
                return
            
            # Add like and update user stats
            db.add_like(user_id, video_id)
            leveled_up = db.increment_user_likes(user_id)
            
            response = f"✅ Спасибо! Вы подтвердили лайк для видео #{video_id}."
            
            if leveled_up:
                user_data = db.get_user(user_id)
                response += f"\n🎉 Поздравляем! Вы достигли уровня {user_data['level']}!"
                
                # Add bonus for level up
                if user_data['level'] > 1:
                    bonus_points = user_data['level'] * 10
                    conn = db.connect()
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE users SET points = points + ? WHERE user_id = ?",
                        (bonus_points, user_id)
                    )
                    conn.commit()
                    conn.close()
                    
                    response += f"\n💰 Бонус за новый уровень: +{bonus_points} очков!"
            
            # Check if this is a streak (multiple likes in a row)
            conn = db.connect()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as streak 
                FROM likes 
                WHERE user_id = ? 
                AND like_time > datetime('now', '-1 day')
            """, (user_id,))
            streak = cursor.fetchone()['streak']
            
            if streak > 0 and streak % 5 == 0:  # Bonus every 5 likes in a day
                streak_bonus = streak // 5 * 15
                cursor.execute(
                    "UPDATE users SET points = points + ? WHERE user_id = ?",
                    (streak_bonus, user_id)
                )
                conn.commit()
                response += f"\n🔥 Бонус за серию лайков: +{streak_bonus} очков!"
            
            conn.close()
            
            await message.reply(response)
            
        except ValueError:
            await message.reply(
                "❌ Пожалуйста, укажите корректный номер видео.\n"
                "Пример: /like 42"
            )
    else:
        await message.reply(
            "Пожалуйста, укажите номер видео после команды.\n"
            "Пример: /like 42\n\n"
            "Используйте /queue для просмотра доступных видео."
        )


@dp.message_handler(commands=['queue'])
async def cmd_queue(message: types.Message):
    """Handle /queue command"""
    if await check_spam(message, 'queue'):
        return
    
    user_id = message.from_user.id
    db.update_user_last_action(user_id)
    
    # Get current queue
    queue = db.get_queue(limit=10)
    
    if not queue:
        await message.reply("📋 Очередь пуста. Будьте первым, кто добавит видео!")
        return
    
    # Format queue message
    queue_text = "📋 Текущая очередь видео:\n\n"
    
    for i, video in enumerate(queue):
        username = video['username'] or f"{video['first_name']} {video['last_name']}".strip()
        liked = "✅" if db.has_liked_video(user_id, video['id']) else "👍"
        queue_text += f"{i+1}. #{video['id']} от {username}: {video['tiktok_url']} [{liked} {video['likes_count']}]\n\n"
    
    queue_text += (
        "Используйте /like [номер] для подтверждения лайка.\n"
        f"Вам нужно лайкнуть {db.get_likes_required()} видео, чтобы добавить своё."
    )
    
    # Add pagination if there are more videos
    conn = db.connect()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM videos")
    total_videos = cursor.fetchone()['count']
    conn.close()
    
    if total_videos > 10:
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("⬅️ Предыдущие", callback_data="queue_prev_0"),
            InlineKeyboardButton("Следующие ➡️", callback_data="queue_next_10")
        )
        await message.reply(queue_text, reply_markup=keyboard)
    else:
        await message.reply(queue_text)


@dp.callback_query_handler(lambda c: c.data.startswith('queue_'))
async def process_queue_pagination(callback_query: types.CallbackQuery):
    """Handle queue pagination"""
    user_id = callback_query.from_user.id
    db.update_user_last_action(user_id)
    
    action, offset_str = callback_query.data.split('_')[1:]
    offset = int(offset_str)
    
    if action == 'prev':
        new_offset = max(0, offset - 10)
    else:  # next
        new_offset = offset
    
    # Get queue with offset
    queue = db.get_queue(limit=10, offset=new_offset)
    
    if not queue:
        await bot.answer_callback_query(callback_query.id, "Нет больше видео в очереди.")
        return
    
    # Format queue message
    queue_text = f"📋 Очередь видео (с {new_offset + 1}):\n\n"
    
    for i, video in enumerate(queue):
        username = video['username'] or f"{video['first_name']} {video['last_name']}".strip()
        liked = "✅" if db.has_liked_video(user_id, video['id']) else "👍"
        queue_text += f"{new_offset + i + 1}. #{video['id']} от {username}: {video['tiktok_url']} [{liked} {video['likes_count']}]\n\n"
    
    queue_text += (
        "Используйте /like [номер] для подтверждения лайка.\n"
        f"Вам нужно лайкнуть {db.get_likes_required()} видео, чтобы добавить своё."
    )
    
    # Add pagination buttons
    conn = db.connect()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM videos")
    total_videos = cursor.fetchone()['count']
    conn.close()
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    if new_offset > 0:
        prev_offset = max(0, new_offset - 10)
        keyboard.insert(InlineKeyboardButton("⬅️ Предыдущие", callback_data=f"queue_prev_{prev_offset}"))
    
    if new_offset + 10 < total_videos:
        next_offset = new_offset + 10
        keyboard.insert(InlineKeyboardButton("Следующие ➡️", callback_data=f"queue_next_{next_offset}"))
    
    await bot.edit_message_text(
        queue_text,
        callback_query.from_user.id,
        callback_query.message.message_id,
        reply_markup=keyboard
    )
    
    await bot.answer_callback_query(callback_query.id)


@dp.message_handler(commands=['status'])
async def cmd_status(message: types.Message):
    """Handle /status command"""
    if await check_spam(message, 'status'):
        return
    
    user_id = message.from_user.id
    db.update_user_last_action(user_id)
    
    user_data = db.get_user(user_id)
    if not user_data:
        await message.reply("❌ Произошла ошибка при получении данных. Пожалуйста, попробуйте /start.")
        return
    
    likes_required = db.get_likes_required()
    likes_given = user_data['likes_given']
    can_submit = likes_given >= likes_required
    
    level_threshold = int(db.get_setting('level_threshold'))
    points_to_next_level = (user_data['level'] * level_threshold) - user_data['points']
    if points_to_next_level < 0:
        points_to_next_level = 0
    
    # Get user rank
    conn = db.connect()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) as rank 
        FROM users 
        WHERE points > (SELECT points FROM users WHERE user_id = ?)
    """, (user_id,))
    rank = cursor.fetchone()['rank'] + 1
    
    cursor.execute("SELECT COUNT(*) as count FROM users")
    total_users = cursor.fetchone()['count']
    
    # Get recent activity
    cursor.execute("""
        SELECT COUNT(*) as today_likes
        FROM likes
        WHERE user_id = ? AND like_time > datetime('now', '-1 day')
    """, (user_id,))
    today_likes = cursor.fetchone()['today_likes']
    
    cursor.execute("""
        SELECT COUNT(*) as today_videos
        FROM videos
        WHERE user_id = ? AND submission_time > datetime('now', '-1 day')
    """, (user_id,))
    today_videos = cursor.fetchone()['today_videos']
    
    conn.close()
    
    # Calculate activity score (0-100%)
    activity_score = min(100, (today_likes * 20) + (today_videos * 30))
    
    status_text = (
        f"📊 Статистика пользователя {get_user_mention(message.from_user)}:\n\n"
        f"👍 Лайков поставлено: {likes_given}\n"
        f"🎬 Видео добавлено: {user_data['videos_submitted']}\n"
        f"⭐ Очков: {user_data['points']}\n"
        f"🏆 Уровень: {user_data['level']}\n"
        f"📈 До следующего уровня: {points_to_next_level} очков\n"
        f"🥇 Ваш ранг: {rank} из {total_users}\n\n"
        f"📅 Активность за 24 часа:\n"
        f"👍 Лайков: {today_likes}\n"
        f"🎬 Видео: {today_videos}\n"
        f"🔋 Уровень активности: {activity_score}%\n\n"
    )
    
    if can_submit:
        status_text += "✅ Вы можете добавить своё видео в очередь!"
    else:
        status_text += f"❗ Вам нужно лайкнуть ещё {likes_required - likes_given} видео, чтобы добавить своё."
    
    # Add achievements
    achievements = []
    if likes_given >= 10:
        achievements.append("🌟 Активный лайкер")
    if likes_given >= 50:
        achievements.append("🌟🌟 Супер лайкер")
    if user_data['videos_submitted'] >= 5:
        achievements.append("📹 Контент-мейкер")
    if user_data['level'] >= 5:
        achievements.append("👑 Ветеран")
    if activity_score >= 80:
        achievements.append("🔥 На огне")
    
    if achievements:
        status_text += "\n\n🏅 Достижения:\n" + "\n".join(achievements)
    
    await message.reply(status_text, parse_mode=ParseMode.MARKDOWN)


@dp.message_handler(commands=['leaderboard'])
async def cmd_leaderboard(message: types.Message):
    """Handle /leaderboard command"""
    if await check_spam(message, 'leaderboard'):
        return
    
    user_id = message.from_user.id
    db.update_user_last_action(user_id)
    
    conn = db.connect()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT user_id, username, first_name, last_name, points, level, likes_given, videos_submitted
        FROM users
        ORDER BY points DESC
        LIMIT 10
    """)
    
    top_users = cursor.fetchall()
    conn.close()
    
    if not top_users:
        await message.reply("📊 Таблица лидеров пуста.")
        return
    
    leaderboard_text = "🏆 Таблица лидеров:\n\n"
    
    for i, user in enumerate(top_users):
        username = user['username'] or f"{user['first_name']} {user['last_name']}".strip()
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
        
        leaderboard_text += (
            f"{medal} {username}: {user['points']} очков (уровень {user['level']})\n"
            f"   👍 {user['likes_given']} лайков | 🎬 {user['videos_submitted']} видео\n\n"
        )
    
    await message.reply(leaderboard_text)


# Admin commands
@dp.message_handler(commands=['admin'])
async def cmd_admin(message: types.Message):
    """Handle /admin command - show admin panel"""
    user_id = message.from_user.id
    
    if not db.is_admin(user_id):
        return
    
    db.update_user_last_action(user_id)
    
    # Create inline keyboard for admin panel
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("👥 Пользователи", callback_data="admin_users"),
        InlineKeyboardButton("🎬 Очередь", callback_data="admin_queue"),
        InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings"),
        InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
    )
    
    await message.reply("🔐 Панель администратора:", reply_markup=keyboard)


# Admin callback handlers
@dp.callback_query_handler(lambda c: c.data.startswith('admin_'))
async def process_admin_callback(callback_query: types.CallbackQuery):
    """Process admin panel callbacks"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    db.update_user_last_action(user_id)
    
    action = callback_query.data.split('_')[1]
    
    if action == "users":
        # Show user management options
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("👑 Добавить админа", callback_data="admin_add_admin"),
            InlineKeyboardButton("🔄 Сбросить лайки", callback_data="admin_reset_likes"),
            InlineKeyboardButton("➕ Добавить очки", callback_data="admin_add_points"),
            InlineKeyboardButton("🔼 Изменить уровень", callback_data="admin_set_level"),
            InlineKeyboardButton("🚫 Заблокировать", callback_data="admin_block_user"),
            InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
        )
        
        await bot.edit_message_text(
            "👥 Управление пользователями:",
            callback_query.from_user.id,
            callback_query.message.message_id,
            reply_markup=keyboard
        )
        
    elif action == "queue":
        # Show queue management options
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("🗑️ Удалить видео", callback_data="admin_delete_video"),
            InlineKeyboardButton("🧹 Очистить очередь", callback_data="admin_clear_queue"),
            InlineKeyboardButton("📢 Объявление", callback_data="admin_announcement"),
            InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
        )
        
        await bot.edit_message_text(
            "🎬 Управление очередью:",
            callback_query.from_user.id,
            callback_query.message.message_id,
            reply_markup=keyboard
        )
        
    elif action == "settings":
        # Show settings options
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("🔢 Лайки для публикации", callback_data="admin_set_likes_required"),
            InlineKeyboardButton("⏱️ Таймаут спама", callback_data="admin_set_spam_timeout"),
            InlineKeyboardButton("⭐ Очки за лайк", callback_data="admin_set_points_per_like"),
            InlineKeyboardButton("🎬 Очки за видео", callback_data="admin_set_points_per_submission"),
            InlineKeyboardButton("📈 Порог уровня", callback_data="admin_set_level_threshold"),
            InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
        )
        
        await bot.edit_message_text(
            "⚙️ Настройки бота:",
            callback_query.from_user.id,
            callback_query.message.message_id,
            reply_markup=keyboard
        )
        
    elif action == "stats":
        # Show bot statistics
        conn = db.connect()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as count FROM users")
        users_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) as count FROM videos")
        videos_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) as count FROM likes")
        likes_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT SUM(points) as total FROM users")
        total_points = cursor.fetchone()['total'] or 0
        
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM users 
            WHERE last_action > datetime('now', '-1 day')
        """)
        active_users = cursor.fetchone()['count']
        
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM videos 
            WHERE submission_time > datetime('now', '-1 day')
        """)
        new_videos = cursor.fetchone()['count']
        
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM likes 
            WHERE like_time > datetime('now', '-1 day')
        """)
        new_likes = cursor.fetchone()['count']
        
        conn.close()
        
        stats_text = (
            "📊 Статистика бота:\n\n"
            f"👥 Пользователей: {users_count}\n"
            f"🎬 Видео в очереди: {videos_count}\n"
            f"👍 Всего лайков: {likes_count}\n"
            f"⭐ Всего очков: {total_points}\n\n"
            f"📅 Активность за 24 часа:\n"
            f"👤 Активных пользователей: {active_users}\n"
            f"🎬 Новых видео: {new_videos}\n"
            f"👍 Новых лайков: {new_likes}\n\n"
            f"⚙️ Настройки:\n"
            f"- Лайков для публикации: {db.get_setting('likes_required')}\n"
            f"- Очков за лайк: {db.get_setting('points_per_like')}\n"
            f"- Очков за публикацию: {db.get_setting('points_per_submission')}\n"
            f"- Порог уровня: {db.get_setting('level_threshold')}\n"
            f"- Таймаут спама: {db.get_setting('spam_timeout')} сек."
        )
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
        
        await bot.edit_message_text(
            stats_text,
            callback_query.from_user.id,
            callback_query.message.message_id,
            reply_markup=keyboard
        )
        
    elif action == "back":
        # Return to main admin panel
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("👥 Пользователи", callback_data="admin_users"),
            InlineKeyboardButton("🎬 Очередь", callback_data="admin_queue"),
            InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings"),
            InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
        )
        
        await bot.edit_message_text(
            "🔐 Панель администратора:",
            callback_query.from_user.id,
            callback_query.message.message_id,
            reply_markup=keyboard
        )
    
    # Answer callback query to remove loading indicator
    await bot.answer_callback_query(callback_query.id)


# Admin action handlers
@dp.callback_query_handler(lambda c: c.data == "admin_delete_video")
async def admin_delete_video(callback_query: types.CallbackQuery):
    """Handle admin delete video action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    await bot.send_message(
        user_id,
        "Введите номер видео, которое нужно удалить из очереди:"
    )
    await BotStates.waiting_for_admin_action.set()
    
    # Store the action type in user data
    state = dp.current_state(user=user_id)
    await state.update_data(admin_action="delete_video")
    
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == "admin_clear_queue")
async def admin_clear_queue(callback_query: types.CallbackQuery):
    """Handle admin clear queue action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    # Create confirmation keyboard
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✅ Да, очистить", callback_data="admin_confirm_clear"),
        InlineKeyboardButton("❌ Отмена", callback_data="admin_back")
    )
    
    await bot.edit_message_text(
        "⚠️ Вы уверены, что хотите очистить всю очередь видео? Это действие нельзя отменить.",
        callback_query.from_user.id,
        callback_query.message.message_id,
        reply_markup=keyboard
    )
    
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == "admin_confirm_clear")
async def admin_confirm_clear_queue(callback_query: types.CallbackQuery):
    """Handle admin confirm clear queue action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    # Clear the queue
    conn = db.connect()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM likes")
    cursor.execute("DELETE FROM videos")
    
    conn.commit()
    conn.close()
    
    await bot.answer_callback_query(callback_query.id, "Очередь успешно очищена!")
    
    # Return to main admin panel
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("👥 Пользователи", callback_data="admin_users"),
        InlineKeyboardButton("🎬 Очередь", callback_data="admin_queue"),
        InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings"),
        InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
    )
    
    await bot.edit_message_text(
        "🔐 Панель администратора:",
        callback_query.from_user.id,
        callback_query.message.message_id,
        reply_markup=keyboard
    )


@dp.callback_query_handler(lambda c: c.data == "admin_add_admin")
async def admin_add_admin(callback_query: types.CallbackQuery):
    """Handle admin add admin action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    await bot.send_message(
        user_id,
        "Введите ID пользователя, которого нужно сделать администратором:"
    )
    await BotStates.waiting_for_admin_user_id.set()
    
    # Store the action type in user data
    state = dp.current_state(user=user_id)
    await state.update_data(admin_action="add_admin")
    
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == "admin_reset_likes")
async def admin_reset_likes(callback_query: types.CallbackQuery):
    """Handle admin reset likes action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    await bot.send_message(
        user_id,
        "Введите ID пользователя, у которого нужно сбросить счетчик лайков:"
    )
    await BotStates.waiting_for_admin_user_id.set()
    
    # Store the action type in user data
    state = dp.current_state(user=user_id)
    await state.update_data(admin_action="reset_likes")
    
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == "admin_add_points")
async def admin_add_points(callback_query: types.CallbackQuery):
    """Handle admin add points action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    await bot.send_message(
        user_id,
        "Введите ID пользователя, которому нужно добавить очки:"
    )
    await BotStates.waiting_for_admin_user_id.set()
    
    # Store the action type in user data
    state = dp.current_state(user=user_id)
    await state.update_data(admin_action="add_points")
    
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == "admin_set_level")
async def admin_set_level(callback_query: types.CallbackQuery):
    """Handle admin set level action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    await bot.send_message(
        user_id,
        "Введите ID пользователя, которому нужно изменить уровень:"
    )
    await BotStates.waiting_for_admin_user_id.set()
    
    # Store the action type in user data
    state = dp.current_state(user=user_id)
    await state.update_data(admin_action="set_level")
    
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == "admin_block_user")
async def admin_block_user(callback_query: types.CallbackQuery):
    """Handle admin block user action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    await bot.send_message(
        user_id,
        "Введите ID пользователя, которого нужно заблокировать:"
    )
    await BotStates.waiting_for_admin_user_id.set()
    
    # Store the action type in user data
    state = dp.current_state(user=user_id)
    await state.update_data(admin_action="block_user")
    
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == "admin_announcement")
async def admin_announcement(callback_query: types.CallbackQuery):
    """Handle admin announcement action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    await bot.send_message(
        user_id,
        "Введите текст объявления для всех пользователей:"
    )
    await BotStates.waiting_for_admin_action.set()
    
    # Store the action type in user data
    state = dp.current_state(user=user_id)
    await state.update_data(admin_action="announcement")
    
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == "admin_set_likes_required")
async def admin_set_likes_required(callback_query: types.CallbackQuery):
    """Handle admin set likes required action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    await bot.send_message(
        user_id,
        "Введите количество лайков, необходимое для публикации видео:"
    )
    await BotStates.waiting_for_admin_action.set()
    
    # Store the action type in user data
    state = dp.current_state(user=user_id)
    await state.update_data(admin_action="set_likes_required")
    
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == "admin_set_spam_timeout")
async def admin_set_spam_timeout(callback_query: types.CallbackQuery):
    """Handle admin set spam timeout action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    await bot.send_message(
        user_id,
        "Введите таймаут защиты от спама в секундах:"
    )
    await BotStates.waiting_for_admin_action.set()
    
    # Store the action type in user data
    state = dp.current_state(user=user_id)
    await state.update_data(admin_action="set_spam_timeout")
    
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == "admin_set_points_per_like")
async def admin_set_points_per_like(callback_query: types.CallbackQuery):
    """Handle admin set points per like action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    await bot.send_message(
        user_id,
        "Введите количество очков за один лайк:"
    )
    await BotStates.waiting_for_admin_action.set()
    
    # Store the action type in user data
    state = dp.current_state(user=user_id)
    await state.update_data(admin_action="set_points_per_like")
    
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == "admin_set_points_per_submission")
async def admin_set_points_per_submission(callback_query: types.CallbackQuery):
    """Handle admin set points per submission action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    await bot.send_message(
        user_id,
        "Введите количество очков за одну публикацию видео:"
    )
    await BotStates.waiting_for_admin_action.set()
    
    # Store the action type in user data
    state = dp.current_state(user=user_id)
    await state.update_data(admin_action="set_points_per_submission")
    
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == "admin_set_level_threshold")
async def admin_set_level_threshold(callback_query: types.CallbackQuery):
    """Handle admin set level threshold action"""
    user_id = callback_query.from_user.id
    
    if not db.is_admin(user_id):
        await bot.answer_callback_query(callback_query.id, "У вас нет прав администратора.")
        return
    
    await bot.send_message(
        user_id,
        "Введите количество очков, необходимое для повышения уровня:"
    )
    await BotStates.waiting_for_admin_action.set()
    
    # Store the action type in user data
    state = dp.current_state(user=user_id)
    await state.update_data(admin_action="set_level_threshold")
    
    await bot.answer_callback_query(callback_query.id)


@dp.message_handler(state=BotStates.waiting_for_admin_user_id)
async def process_admin_user_id(message: types.Message, state: FSMContext):
    """Process admin user ID input"""
    admin_id = message.from_user.id
    
    if not db.is_admin(admin_id):
        await state.finish()
        return
    
    # Get the action type from user data
    user_data = await state.get_data()
    action = user_data.get('admin_action')
    
    try:
        target_user_id = int(message.text.strip())
        target_user = db.get_user(target_user_id)
        
        if not target_user:
            await message.reply(f"❌ Пользователь с ID {target_user_id} не найден.")
            await state.finish()
            return
        
        if action == "add_admin":
            db.set_admin_status(target_user_id, True)
            await message.reply(f"✅ Пользователь с ID {target_user_id} теперь администратор.")
            await state.finish()
            
        elif action == "reset_likes":
            conn = db.connect()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET likes_given = 0 WHERE user_id = ?", (target_user_id,))
            conn.commit()
            conn.close()
            await message.reply(f"✅ Счетчик лайков пользователя с ID {target_user_id} сброшен.")
            await state.finish()
            
        elif action == "add_points":
            await message.reply(f"Введите количество очков для добавления пользователю с ID {target_user_id}:")
            await BotStates.waiting_for_admin_points.set()
            await state.update_data(target_user_id=target_user_id)
            
        elif action == "set_level":
            await message.reply(f"Введите новый уровень для пользователя с ID {target_user_id}:")
            await BotStates.waiting_for_admin_level.set()
            await state.update_data(target_user_id=target_user_id)
            
        elif action == "block_user":
            # Create a spam protection record with a very long timeout
            conn = db.connect()
            cursor = conn.cursor()
            
            # Block for all common commands
            for cmd in ['start', 'submit', 'like', 'queue', 'status', 'leaderboard']:
                cursor.execute(
                    "INSERT OR REPLACE INTO spam_protection (user_id, command, timestamp) VALUES (?, ?, datetime('now', '+100 years'))",
                    (target_user_id, cmd)
                )
            
            conn.commit()
            conn.close()
            
            await message.reply(f"✅ Пользователь с ID {target_user_id} заблокирован.")
            await state.finish()
            
    except ValueError:
        await message.reply("❌ Пожалуйста, введите корректный ID пользователя (число).")
        await state.finish()


@dp.message_handler(state=BotStates.waiting_for_admin_points)
async def process_admin_points(message: types.Message, state: FSMContext):
    """Process admin points input"""
    admin_id = message.from_user.id
    
    if not db.is_admin(admin_id):
        await state.finish()
        return
    
    # Get the target user ID from user data
    user_data = await state.get_data()
    target_user_id = user_data.get('target_user_id')
    
    try:
        points = int(message.text.strip())
        
        conn = db.connect()
        cursor = conn.cursor()
        
        # Add points
        cursor.execute(
            "UPDATE users SET points = points + ? WHERE user_id = ?",
            (points, target_user_id)
        )
        
        # Check if user should level up
        cursor.execute("SELECT points, level FROM users WHERE user_id = ?", (target_user_id,))
        user = cursor.fetchone()
        
        cursor.execute("SELECT value FROM settings WHERE key = 'level_threshold'")
        level_threshold = int(cursor.fetchone()['value'])
        
        new_level = (user['points'] // level_threshold) + 1
        if new_level > user['level']:
            cursor.execute(
                "UPDATE users SET level = ? WHERE user_id = ?",
                (new_level, target_user_id)
            )
            
            await message.reply(
                f"✅ Добавлено {points} очков пользователю с ID {target_user_id}.\n"
                f"🎉 Пользователь повышен до уровня {new_level}!"
            )
        else:
            await message.reply(f"✅ Добавлено {points} очков пользователю с ID {target_user_id}.")
        
        conn.commit()
        conn.close()
        
    except ValueError:
        await message.reply("❌ Пожалуйста, введите корректное количество очков (число).")
    
    await state.finish()


@dp.message_handler(state=BotStates.waiting_for_admin_level)
async def process_admin_level(message: types.Message, state: FSMContext):
    """Process admin level input"""
    admin_id = message.from_user.id
    
    if not db.is_admin(admin_id):
        await state.finish()
        return
    
    # Get the target user ID from user data
    user_data = await state.get_data()
    target_user_id = user_data.get('target_user_id')
    
    try:
        level = int(message.text.strip())
        
        if level < 1:
            await message.reply("❌ Уровень не может быть меньше 1.")
            await state.finish()
            return
        
        conn = db.connect()
        cursor = conn.cursor()
        
        # Set level
        cursor.execute(
            "UPDATE users SET level = ? WHERE user_id = ?",
            (level, target_user_id)
        )
        
        conn.commit()
        conn.close()
        
        await message.reply(f"✅ Уровень пользователя с ID {target_user_id} изменен на {level}.")
        
    except ValueError:
        await message.reply("❌ Пожалуйста, введите корректный уровень (число).")
    
    await state.finish()


@dp.message_handler(state=BotStates.waiting_for_admin_action)
async def process_admin_action(message: types.Message, state: FSMContext):
    """Process admin action input"""
    user_id = message.from_user.id
    
    if not db.is_admin(user_id):
        await state.finish()
        return
    
    # Get the action type from user data
    user_data = await state.get_data()
    action = user_data.get('admin_action')
    
    if action == "delete_video":
        try:
            video_id = int(message.text.strip())
            video = db.get_video(video_id)
            
            if not video:
                await message.reply(f"❌ Видео с номером {video_id} не найдено в очереди.")
            else:
                db.delete_video(video_id)
                await message.reply(f"✅ Видео #{video_id} успешно удалено из очереди.")
        except ValueError:
            await message.reply("❌ Пожалуйста, введите корректный номер видео.")
    
    elif action == "set_likes_required":
        try:
            likes_required = int(message.text.strip())
            
            if likes_required < 0:
                await message.reply("❌ Количество лайков не может быть отрицательным.")
            else:
                db.update_setting('likes_required', str(likes_required))
                await message.reply(f"✅ Количество лайков для публикации установлено: {likes_required}")
        except ValueError:
            await message.reply("❌ Пожалуйста, введите корректное число.")
    
    elif action == "set_spam_timeout":
        try:
            spam_timeout = int(message.text.strip())
            
            if spam_timeout < 0:
                await message.reply("❌ Таймаут не может быть отрицательным.")
            else:
                db.update_setting('spam_timeout', str(spam_timeout))
                await message.reply(f"✅ Таймаут защиты от спама установлен: {spam_timeout} сек.")
        except ValueError:
            await message.reply("❌ Пожалуйста, введите корректное число.")
    
    elif action == "set_points_per_like":
        try:
            points = int(message.text.strip())
            
            if points < 0:
                await message.reply("❌ Количество очков не может быть отрицательным.")
            else:
                db.update_setting('points_per_like', str(points))
                await message.reply(f"✅ Количество очков за лайк установлено: {points}")
        except ValueError:
            await message.reply("❌ Пожалуйста, введите корректное число.")
    
    elif action == "set_points_per_submission":
        try:
            points = int(message.text.strip())
            
            if points < 0:
                await message.reply("❌ Количество очков не может быть отрицательным.")
            else:
                db.update_setting('points_per_submission', str(points))
                await message.reply(f"✅ Количество очков за публикацию установлено: {points}")
        except ValueError:
            await message.reply("❌ Пожалуйста, введите корректное число.")
    
    elif action == "set_level_threshold":
        try:
            threshold = int(message.text.strip())
            
            if threshold < 1:
                await message.reply("❌ Порог уровня не может быть меньше 1.")
            else:
                db.update_setting('level_threshold', str(threshold))
                await message.reply(f"✅ Порог уровня установлен: {threshold} очков")
        except ValueError:
            await message.reply("❌ Пожалуйста, введите корректное число.")
    
    elif action == "announcement":
        announcement_text = message.text.strip()
        
        if not announcement_text:
            await message.reply("❌ Текст объявления не может быть пустым.")
        else:
            # Get all users
            conn = db.connect()
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            users = cursor.fetchall()
            conn.close()
            
            sent_count = 0
            
            # Send announcement to all users
            for user in users:
                try:
                    await bot.send_message(
                        user['user_id'],
                        f"📢 ОБЪЯВЛЕНИЕ\n\n{announcement_text}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    sent_count += 1
                except Exception as e:
                    logging.error(f"Failed to send announcement to user {user['user_id']}: {e}")
            
            await message.reply(f"✅ Объявление отправлено {sent_count} пользователям.")
    
    # Clear state
    await state.finish()


# Error handler
@dp.errors_handler()
async def error_handler(update, exception):
    """Handle errors"""
    logging.exception(f"Error handling update {update}: {exception}")
    
    # Try to notify user about error
    if isinstance(update, types.Message):
        await update.reply("❌ Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте позже.")
    
    return True


# Main function to start the bot
async def on_startup(dp):
    """Actions to perform on startup"""
    logging.info("Starting bot...")
    
    # Set default commands
    await dp.bot.set_my_commands([
        types.BotCommand("start", "Начать работу с ботом"),
        types.BotCommand("submit", "Отправить видео в очередь"),
        types.BotCommand("like", "Подтвердить лайк видео"),
        types.BotCommand("queue", "Показать очередь видео"),
        types.BotCommand("status", "Показать вашу статистику"),
        types.BotCommand("leaderboard", "Показать таблицу лидеров"),
        types.BotCommand("admin", "Панель администратора (только для админов)")
    ])


if __name__ == '__main__':
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
