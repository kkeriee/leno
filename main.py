import os
import logging
import asyncio
import threading
import time
import re
import random
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from openai import OpenAI
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    BotCommand,
    constants
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
    CallbackQueryHandler
)
from database import (
    add_referral,
    get_referrer_id,
    get_referral_count,
    set_bonus_count,
    get_bonus_count,
    increment_daily_counter,
    get_daily_counter,
    cleanup_old_counters
)

# Настройка логгирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка конфигурации
TOKEN = os.getenv("TG_TOKEN")
NOVITA_API_KEY = os.getenv("NOVITA_API_KEY")
BOT_USERNAME = os.getenv("BOT_USERNAME", "@lenaneyrobot")

# Идентификатор разработчика
DEVELOPER_ID = 1003817394

# Идентификатор чата без ограничений
UNLIMITED_CHAT_ID = -1001481824277

# Состояния для ConversationHandler разработчика
SELECT_USER, SELECT_ACTION, INPUT_AMOUNT = range(3)

# Глобальные переменные
user_contexts = {}
last_cleanup_time = time.time()

# Список эмодзи для использования
EMOJI_LIST = ["😌", "😊", "💖", "🌙", "🎭", "🤍", "💫", "🥀", "🥂", "😒"]

# Загрузка персонажа с ОБЯЗАТЕЛЬНЫМИ инструкциями
try:
    with open("persona.txt", "r", encoding="utf-8") as f:
        PERSONA = f.read().strip()
except Exception as e:
    logger.error(f"Error loading persona: {e}")
    PERSONA = "Ты девушка, тебе 18 лет, тебя зовут Лена Тихонова, ты застенчивая меланхоличная девушка с фиолетовыми хвостами и зелёными глазами. Ты любишь читать, избегаешь людей, твой сюжет — тонкий баланс между хрупкостью и силой, ведущий либо к семейному счастью, либо к трагедии."

# Всегда добавляем системные инструкции
PERSONA += (
    "\n\nТы общаешься в чате с разными пользователями. "
    "Обращайся к ним по именам (используй только первое имя). "
    "Учитывай историю переписки с каждым пользователем отдельно. "
    "Сообщения пользователей начинаются с их имени в формате 'Имя: текст'. "
    "Все действия описывай в формате *действие*. "
    "Всегда завершай сообщение полностью. "
    "Форматируй ответы с абзацами и отступами, где это уместно."
)

# Функция проверки лимита сообщений
def check_message_limit(user_id: int) -> bool:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    
    # Очистка старых записей перед проверкой
    global last_cleanup_time
    current_time = time.time()
    if current_time - last_cleanup_time > 1800:
        cleanup_old_counters()
        last_cleanup_time = current_time
    
    # Базовый лимит
    base_limit = 35
    
    # Бонус за рефералов
    referral_bonus = get_referral_count(user_id) * 3
    
    # Постоянные бонусные сообщения
    bonus_messages = get_bonus_count(user_id)
    
    # Общий доступный лимит
    total_limit = base_limit + referral_bonus + bonus_messages
    
    # Получение текущего счетчика
    current_count = get_daily_counter(user_id, today)
    
    # Проверка лимита
    if current_count >= total_limit:
        return False
    
    return True

# Функция для форматирования действий
def format_actions(text: str) -> str:
    return text

# Функция для добавления эмодзи
def add_emojis(text: str) -> str:
    if not text:
        return text
    
    if random.random() < 0.2:
        selected_emoji = random.choice(EMOJI_LIST)
        if text[-1] not in EMOJI_LIST:
            return text + selected_emoji
    return text

# Функция для завершения незаконченных предложений
def complete_sentences(text: str) -> str:
    if not text:
        return text
    
    if not re.search(r'[.!?…]$', text):
        text += '.'
    
    return text

# Функция для форматирования абзацев
def format_paragraphs(text: str) -> str:
    paragraphs = text.split('\n\n')
    formatted = []
    for paragraph in paragraphs:
        if paragraph.strip():
            cleaned = re.sub(r'\s+', ' ', paragraph).strip()
            formatted.append(cleaned)
    
    return '\n\n'.join(formatted)

# Функция для очистки ответа
def clean_response(response: str) -> str:
    cleaned = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
    cleaned = cleaned.replace('<think>', '').replace('</think>', '')
    cleaned = cleaned.replace('</s>', '').replace('<s>', '')
    
    cleaned = format_actions(cleaned)
    cleaned = re.sub(r'\n\s*\n', '\n\n', cleaned).strip()
    cleaned = complete_sentences(cleaned)
    cleaned = format_paragraphs(cleaned)
    cleaned = add_emojis(cleaned)
    
    return cleaned

# HTTP-сервер для проверки работоспособности
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Service is alive')
    
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_http_server(port=8080):
    server_address = ('', port)
    httpd = HTTPServer(server_address, HealthHandler)
    logger.info(f"Starting HTTP health check server on port {port}")
    httpd.serve_forever()

# Запрос к DeepSeek через Novita API
def query_chat(messages: list) -> str:
    try:
        client = OpenAI(
            base_url="https://api.novita.ai/v3/openai",
            api_key=NOVITA_API_KEY,
        )
        
        response = client.chat.completions.create(
            model="deepseek/deepseek-r1-0528",
            messages=messages,
            temperature=0.7,
            max_tokens=600,
            stream=False,
            response_format={"type": "text"}
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Novita API error: {e}")
        return "Произошла ошибка при обработке запроса. Попробуйте позже."

# Обработчик команды /buy
async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    card_number = "2200 2480 7637 0799"
    
    text = (
        "💎 <b>Здесь вы можете купить запросы</b> 💎\n\n"
        "❓ <b>Как оплатить запросы в боте?</b> ❓\n"
        "- 10 рублей = 1 запрос.\n"
        f"- Вам необходимо отправить нужную сумму на карту: <code>{card_number}</code>\n"
        f"- В сообщении к переводу обязательно укажите ваш Telegram ID: <code>{user.id}</code>\n"
        "- В течении некоторого времени вам будут начислены бонусные запросы в боте.\n"
        "- Если у вас возникли проблемы или вы хотите задать вопросы по покупке запросов, "
        "то вы можете связаться напрямую с разработчиком - <a href='https://t.me/kiojomi'>kiojomi</a>"
    )
    
    await update.message.reply_text(text, parse_mode="HTML")

# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    
    if context.args and context.args[0].isdigit():
        referrer_id = int(context.args[0])
        if referrer_id != user.id and not get_referrer_id(user.id):
            add_referral(user.id, referrer_id)
            logger.info(f"New referral: user {user.id} invited by {referrer_id}")
    
    await update.message.reply_text(
        "Привет... Я Лена. Рада тебя видеть... может, позже прогуляемся? Я покажу рисунки... или просто посидим, если хочешь. P.S. Если увидишь Ульяну с кузнечиком... предупреди, пожалуйста? ^-^\n\n"
        "/info - информация обо мне и как правильно ко мне обращаться.\n"
        "/stat - узнать свой статус и оставшиеся сообщения\n"
        "/ref - ваша реферальная программа\n"
        "/buy - купить дополнительные запросы"
    )

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Информация", url="https://telegra.ph/O-Lene-Tihonovoj-07-11")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "❗️Здесь вы можете ознакомиться с правилами использования нашего бота.\n"
        "Рекомендуем прочитать перед использованием.",
        reply_markup=reply_markup
    )

async def ref_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user.id}"
    count = get_referral_count(user.id)
    
    # Рассчитать общий доступный лимит для пользователя
    today = datetime.utcnow().strftime("%Y-%m-%d")
    base_limit = 35
    referral_bonus = count * 3
    bonus_messages = get_bonus_count(user.id)
    total_limit = base_limit + referral_bonus + bonus_messages
    
    await update.message.reply_text(
        f"👥 <b>Ваша реферальная программа</b>\n\n"
        f"• Ваша ссылка: <code>{ref_link}</code>\n"
        f"• Приглашено пользователей: {count}\n"
        f"• Каждый приглашенный пользователь увеличивает ваш дневной лимит на +3 сообщения\n"
        f"• Текущий доступный лимит: <b>{total_limit}</b> сообщений в день\n\n"
        f"Поделитесь своей ссылкой с друзьями, чтобы увеличить количество доступных сообщений!\n\n"
        f"💎 Также вы можете <b>купить дополнительные запросы</b> командой /buy",
        parse_mode="HTML"
    )

async def clear_context(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat_id = update.message.chat_id
    key = (chat_id, user.id)
    
    if key in user_contexts:
        del user_contexts[key]
        logger.info(f"Context cleared for user {user.full_name} in chat {chat_id}")
        await update.message.reply_text("История диалога очищена. Начнем заново!")
    else:
        await update.message.reply_text("У тебя еще нет истории диалога со мной!")

async def stat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    today = datetime.utcnow().strftime("%Y-%m-%d")
    
    has_context = any(ctx_key[1] == user.id for ctx_key in user_contexts.keys())
    
    used_messages = get_daily_counter(user.id, today)
    
    base_limit = 35
    referral_count = get_referral_count(user.id)
    referral_bonus = referral_count * 3
    bonus_messages = get_bonus_count(user.id)
    total_limit = base_limit + referral_bonus + bonus_messages
    remaining = max(0, total_limit - used_messages)
    
    # Проверяем, является ли чат безлимитным
    is_unlimited = update.message.chat_id == UNLIMITED_CHAT_ID
    
    unlimited_info = "\n• Вы находитесь в безлимитном чате" if is_unlimited else ""
    
    message = (
        f"📊 <b>Ваш статус:</b>\n"
        f"{unlimited_info}\n\n"
        f"• Базовый лимит: {base_limit}\n"
        f"• Бонус за рефералов: +{referral_bonus} (приглашено: {referral_count})\n"
        f"• Бонусные сообщения: +{bonus_messages}\n"
        f"• Итого доступно: <b>{total_limit}</b>\n"
        f"• Использовано: {used_messages}\n"
        f"• Осталось: <b>{remaining}</b>\n\n"
        f"• История диалога: {'сохранена' if has_context else 'отсутствует'}\n\n"
        f"💡 Для сброса истории используйте /clear\n"
        f"👥 Приглашайте друзей: /ref\n"
        f"💎 Купить дополнительные запросы: /buy"
    )
    
    await update.message.reply_text(message, parse_mode="HTML")

# Обработчик команды /dev
async def dev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    
    if user.id != DEVELOPER_ID:
        logger.warning(f"User {user.id} tried to access dev command")
        await update.message.reply_text("У вас нет прав для использования этой команды.")
        return
    
    await update.message.reply_text(
        "🔧 <b>Режим разработчика</b>\n\n"
        "Введите ID пользователя, с которым хотите работать:",
        parse_mode="HTML"
    )
    
    return SELECT_USER

# Обработка введенного ID пользователя
async def select_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    
    if not user_input.isdigit():
        await update.message.reply_text("❌ ID пользователя должен быть числом. Попробуйте еще раз:")
        return SELECT_USER
    
    user_id = int(user_input)
    context.user_data['target_user_id'] = user_id
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить сообщения", callback_data="add_messages")],
        [InlineKeyboardButton("➖ Убрать сообщения", callback_data="remove_messages")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👤 Выбран пользователь с ID: {user_id}\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )
    
    return SELECT_ACTION

# Обработка выбора действия
async def select_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action = query.data
    context.user_data['action'] = action
    
    action_text = "добавить" if action == "add_messages" else "убрать"
    
    await query.edit_message_text(
        f"✏️ Введите количество сообщений для {action_text}:"
    )
    
    return INPUT_AMOUNT

# Обработка ввода количества сообщений
async def input_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    
    if not user_input.isdigit():
        await update.message.reply_text("❌ Количество сообщений должно быть числом. Попробуйте еще раз:")
        return INPUT_AMOUNT
    
    amount = int(user_input)
    target_user_id = context.user_data['target_user_id']
    action = context.user_data['action']
    
    # Работа с постоянными бонусами
    current_bonus = get_bonus_count(target_user_id)
    
    if action == "add_messages":
        new_bonus = current_bonus + amount
        set_bonus_count(target_user_id, new_bonus)
        action_result = "добавлены"
    else:
        new_bonus = max(0, current_bonus - amount)
        set_bonus_count(target_user_id, new_bonus)
        action_result = "убраны"
    
    base_limit = 35
    referral_bonus = get_referral_count(target_user_id) * 3
    total_limit = base_limit + referral_bonus + new_bonus
    
    report = (
        f"✅ Успешно!\n\n"
        f"• Пользователь ID: {target_user_id}\n"
        f"• Действие: {action_result} {amount} бонусных сообщений\n"
        f"• Текущие бонусные сообщения: {new_bonus}\n"
        f"• Общий доступный лимит: {total_limit} ({base_limit} базовых + {referral_bonus} реферальных + {new_bonus} бонусных)"
    )
    
    await update.message.reply_text(report)
    return ConversationHandler.END

# Отмена диалога разработчика
async def cancel_dev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Операция отменена.")
    return ConversationHandler.END

# Обработка сообщений с учетом лимитов
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = message.from_user
    chat_id = message.chat_id
    key = (chat_id, user.id)
    
    if not message.text:
        return
    
    # Улучшенная обработка групповых чатов
    bot_username = (await context.bot.get_me()).username
    is_private = message.chat.type == "private"
    is_unlimited = chat_id == UNLIMITED_CHAT_ID
    bot_mention = f"@{bot_username}"
    
    # Проверка, является ли сообщение адресованным боту
    is_reply_to_bot = (
        message.reply_to_message and 
        message.reply_to_message.from_user.username == bot_username
    )
    is_mention = bot_mention in message.text
    is_bot_name_in_text = bot_username in message.text.lower()
    
    # Для групповых чатов реагируем только на:
    # 1. Ответы на сообщения бота
    # 2. Сообщения с упоминанием бота (@username)
    # 3. Сообщения с именем бота в тексте (без @)
    is_addressed_to_bot = is_reply_to_bot or is_mention or is_bot_name_in_text
    
    # В групповых чатах (не приватных) игнорируем сообщения не адресованные боту
    if not is_private and not is_addressed_to_bot:
        return
    
    # Проверка лимита сообщений (только для обычных чатов)
    if not is_unlimited:
        # Проверяем лимит перед увеличением счетчика
        if not check_message_limit(user.id):
            logger.warning(f"User {user.full_name} ({user.id}) exceeded daily message limit")
            
            today = datetime.utcnow().strftime("%Y-%m-%d")
            base_limit = 35
            referral_bonus = get_referral_count(user.id) * 3
            bonus_messages = get_bonus_count(user.id)
            total_limit = base_limit + referral_bonus + bonus_messages
            
            await message.reply_text(
                f"❗️Вы достигли ежедневного лимита на общение с Леной ({total_limit} сообщений).\n"
                "Возвращайтесь завтра или продолжите безлимитно ей пользоваться в чате - "
                "https://t.me/freedom346\n\n"
                "Или вы можете:\n"
                "• Увеличить число дневных запросов через реферальную программу: /ref\n"
                "• Купить дополнительные запросы: /buy"
            )
            return
        
        # Увеличиваем счетчик сообщений только если лимит не превышен
        today = datetime.utcnow().strftime("%Y-%m-%d")
        increment_daily_counter(user.id, today)
    
    logger.info(f"Обработка сообщения от {user.full_name} в чате {chat_id}: {message.text}")
    
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    
    try:
        history = user_contexts.get(key, [])
        user_message_content = f"{user.full_name}: {message.text}"
        user_message = {"role": "user", "content": user_message_content}
        
        messages = [{"role": "system", "content": PERSONA}]
        messages.extend(history)
        messages.append(user_message)
        
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, query_chat, messages)
        cleaned_response = clean_response(response)
        
        if not cleaned_response.strip():
            cleaned_response = "Я обдумываю твой вопрос... Попробуй спросить по-другому."
        
        history.append(user_message)
        history.append({"role": "assistant", "content": cleaned_response})
        
        if len(history) > 10:
            history = history[-10:]
        
        user_contexts[key] = history
        
        # Отправляем ответ без форматирования Markdown
        await message.reply_text(cleaned_response)
            
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")
        await message.reply_text("Что-то пошло не так. Попробуйте еще раз.")

async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "Начало работы с ботом"),
        BotCommand("info", "Информация о боте и правила использования"),
        BotCommand("clear", "Очистить историю диалога"),
        BotCommand("stat", "Статус и оставшиеся сообщения"),
        BotCommand("ref", "Реферальная программа"),
        BotCommand("buy", "Купить дополнительные запросы")
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Меню команд бота установлено")

def main():
    if not TOKEN:
        logger.error("TG_TOKEN environment variable is missing!")
        return
    if not NOVITA_API_KEY:
        logger.error("NOVITA_API_KEY environment variable is missing!")
        return

    # Запуск HTTP-сервера
    port = int(os.getenv('PORT', 8080))
    http_thread = threading.Thread(target=run_http_server, args=(port,), daemon=True)
    http_thread.start()

    logger.info("Ожидание 45 секунд перед запуском бота...")
    time.sleep(45)

    application = Application.builder().token(TOKEN).post_init(post_init).build()
    
    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("ref", ref_command))
    application.add_handler(CommandHandler("clear", clear_context))
    application.add_handler(CommandHandler("stat", stat))
    application.add_handler(CommandHandler("buy", buy_command))
    
    # Скрытая команда для разработчика
    dev_handler = ConversationHandler(
        entry_points=[CommandHandler("dev", dev)],
        states={
            SELECT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_user)],
            SELECT_ACTION: [CallbackQueryHandler(select_action)],
            INPUT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_amount)]
        },
        fallbacks=[CommandHandler("cancel", cancel_dev)],
        allow_reentry=True
    )
    application.add_handler(dev_handler)
    
    # Основной обработчик сообщений
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    
    logger.info("Запуск бота в режиме polling...")
    
    poll_params = {
        "drop_pending_updates": True,
        "close_loop": False,
        "stop_signals": [],
        "connect_timeout": 60,
        "read_timeout": 60,
        "pool_timeout": 60
    }
    
    application.run_polling(**poll_params)

if __name__ == "__main__":
    main()
