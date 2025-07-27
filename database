import sqlite3
import os
import logging
from datetime import datetime

# Настройка логгирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_FILE = "bot_data.db"

def init_db():
    """Инициализация базы данных и создание таблиц"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # Таблица рефералов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    invited_id INTEGER PRIMARY KEY,
                    referrer_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            ''')
            
            # Таблица бонусных сообщений
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bonus_messages (
                    user_id INTEGER PRIMARY KEY,
                    bonus_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            # Таблица счетчиков сообщений (для ежедневных лимитов)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_counters (
                    user_id INTEGER,
                    date TEXT,
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, date)
                )
            ''')
            
            conn.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")

def add_referral(invited_id: int, referrer_id: int):
    """Добавление реферальной связи"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO referrals (invited_id, referrer_id, created_at) VALUES (?, ?, ?)",
                (invited_id, referrer_id, datetime.utcnow().isoformat())
            )
            conn.commit()
        logger.info(f"Referral added: invited_id={invited_id}, referrer_id={referrer_id}")
    except Exception as e:
        logger.error(f"Error adding referral: {e}")

def get_referrer_id(invited_id: int) -> int:
    """Получение ID реферера для пользователя"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT referrer_id FROM referrals WHERE invited_id = ?",
                (invited_id,)
            )
            result = cursor.fetchone()
            return result[0] if result else None
    except Exception as e:
        logger.error(f"Error getting referrer ID: {e}")
        return None

def get_referral_count(referrer_id: int) -> int:
    """Получение количества рефералов для пользователя"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?",
                (referrer_id,)
            )
            result = cursor.fetchone()
            return result[0] if result else 0
    except Exception as e:
        logger.error(f"Error getting referral count: {e}")
        return 0

def set_bonus_count(user_id: int, bonus_count: int):
    """Установка количества бонусных сообщений для пользователя"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT OR REPLACE INTO bonus_messages 
                (user_id, bonus_count, updated_at) 
                VALUES (?, ?, ?)''',
                (user_id, bonus_count, datetime.utcnow().isoformat())
            )
            conn.commit()
        logger.info(f"Bonus count set: user_id={user_id}, count={bonus_count}")
    except Exception as e:
        logger.error(f"Error setting bonus count: {e}")

def get_bonus_count(user_id: int) -> int:
    """Получение количества бонусных сообщений для пользователя"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT bonus_count FROM bonus_messages WHERE user_id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            return result[0] if result else 0
    except Exception as e:
        logger.error(f"Error getting bonus count: {e}")
        return 0

def increment_daily_counter(user_id: int, date: str):
    """Увеличение счетчика сообщений для пользователя на указанную дату"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            # Увеличиваем счетчик или создаем новую запись
            cursor.execute(
                '''INSERT INTO daily_counters (user_id, date, count)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, date) DO UPDATE SET count = count + 1''',
                (user_id, date)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error incrementing daily counter: {e}")

def get_daily_counter(user_id: int, date: str) -> int:
    """Получение счетчика сообщений для пользователя на указанную дату"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT count FROM daily_counters WHERE user_id = ? AND date = ?",
                (user_id, date)
            )
            result = cursor.fetchone()
            return result[0] if result else 0
    except Exception as e:
        logger.error(f"Error getting daily counter: {e}")
        return 0

def cleanup_old_counters():
    """Очистка устаревших счетчиков сообщений (старше 1 дня)"""
    try:
        today = datetime.utcnow().date()
        cutoff_date = (today - timedelta(days=1)).isoformat()
        
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM daily_counters WHERE date < ?",
                (cutoff_date,)
            )
            conn.commit()
        logger.info("Old counters cleaned up successfully")
    except Exception as e:
        logger.error(f"Error cleaning up old counters: {e}")

# Инициализируем базу данных при импорте модуля
init_db()
