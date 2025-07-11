import logging
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from telegram.error import BadRequest
import sqlite3
import asyncio

# Конфигурация
BOT_TOKEN = '7533186679:AAE7LFm6Q-GyxAHv3DiTd5nAezo_vKj2HE0'
ADMIN_ID = 7575193973
GROUP_ID = -1002806710253  # Ваша группа
DB_NAME = 'users.db'

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            phone_number TEXT,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invite_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    conn.commit()
    conn.close()

# Функции для работы с базой данных
def add_user(update: Update):
    user = update.effective_user
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
        VALUES (?, ?, ?, ?)
    ''', (user.id, user.username, user.first_name, user.last_name))
    
    conn.commit()
    conn.close()

def log_action(user_id, action):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO user_actions (user_id, action) VALUES (?, ?)', (user_id, action))
    conn.commit()
    conn.close()

def add_invite_link(user_id, link):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO invite_links (user_id, link) VALUES (?, ?)', (user_id, link))
    conn.commit()
    conn.close()

def deactivate_link(link):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE invite_links SET is_active = 0 WHERE link = ?', (link,))
    conn.commit()
    conn.close()

# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_user(update)
    log_action(update.effective_user.id, 'started bot')
    
    keyboard = [
        [InlineKeyboardButton("📩 Получить ссылку", callback_data='get_link')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 Добро пожаловать в *Переходник DataNex*!\n\n"
        "Нажмите кнопку ниже, чтобы получить временную ссылку для вступления в группу.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'get_link':
        user = query.from_user
        log_action(user.id, 'requested link')
        
        keyboard = [
            [InlineKeyboardButton("✅ Я согласен", callback_data='confirm_link')],
            [InlineKeyboardButton("❌ Отмена", callback_data='cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "⚠️ *Внимание!*\n\n"
            "Ссылка будет действительна только *20 секунд*. "
            "Вы должны успеть перейти по ней в течение этого времени.\n\n"
            "Вы согласны с этими условиями?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == 'confirm_link':
        user = query.from_user
        bot = context.bot
        
        try:
            invite_link = await bot.create_chat_invite_link(
                chat_id=GROUP_ID,
                member_limit=1,
                creates_join_request=False
            )
            
            add_invite_link(user.id, invite_link.invite_link)
            
            await query.edit_message_text(
                f"🔗 Ваша ссылка для вступления:\n\n"
                f"{invite_link.invite_link}\n\n"
                f"⏳ Ссылка будет активна *20 секунд*!",
                parse_mode='Markdown'
            )
            
            admin_message = (
                f"👤 Пользователь:\n"
                f"ID: {user.id}\n"
                f"Username: @{user.username if user.username else 'N/A'}\n"
                f"Имя: {user.first_name}\n"
                f"Создал ссылку: {invite_link.invite_link}"
            )
            await bot.send_message(ADMIN_ID, admin_message)
            
            # Запланировать удаление ссылки через 20 секунд
            asyncio.create_task(delete_link_after_delay(bot, invite_link.invite_link, user.id))
            
        except Exception as e:
            logger.error(f"Error creating invite link: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка при создании ссылки. Пожалуйста, попробуйте позже."
            )
    
    elif query.data == 'cancel':
        await query.edit_message_text("🚫 Действие отменено. Нажмите /start чтобы начать заново.")

async def delete_link_after_delay(bot, link, user_id):
    await asyncio.sleep(20)
    
    try:
        await bot.revoke_chat_invite_link(
            chat_id=GROUP_ID,
            invite_link=link
        )
        deactivate_link(link)
        
        await bot.send_message(
            user_id,
            "🕒 Время действия ссылки истекло! Если вы не успели вступить, "
            "нажмите /start чтобы получить новую ссылку."
        )
        
    except BadRequest as e:
        if "invite link revoked" in str(e):
            logger.info(f"Link already revoked: {link}")
        else:
            logger.error(f"Error revoking invite link: {e}")
    except Exception as e:
        logger.error(f"Error in delete_link: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    if update and update.effective_user:
        await context.bot.send_message(
            update.effective_user.id,
            "❌ Произошла ошибка. Пожалуйста, попробуйте позже."
        )

def main():
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_error_handler(error_handler)
    
    logger.info("Bot started")
    application.run_polling()

if __name__ == '__main__':
    main()