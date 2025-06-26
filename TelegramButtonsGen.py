# --- ENGLISH DESCRIPTION ---
#
# Module: TelegramButtonsGen.py
#
# Description:
# This module provides a stateful service for sending interactive messages
# with inline buttons through a Telegram bot and retrieving the user's selection.
#
# Design Philosophy:
# - It is designed to be imported and used by a primary, host application (e.g., a multi-threaded script).
# - It operates on an asyncio event loop that is provided and managed by the host application.
# - It maintains a single, persistent bot instance across multiple calls to avoid
#   the overhead and instability of creating/destroying the bot for each message.
# - Lazy Initialization: The bot instance is created and started on the very first call
#   to `send_message_with_buttons`, then reused for all subsequent calls.
#
# Public API:
# - async def send_message_with_buttons(text: str, button_names: list, time_out: int = 60) -> str:
#   - Sends a message with buttons and waits for a user response.
#   - Returns the callback_data of the pressed button (as a string, e.g., "1", "2").
#   - Returns "-1" on timeout.
#   - Returns "-2" on an internal error.
#
# - async def cleanup_bot():
#   - Gracefully shuts down the persistent bot instance.
#   - Intended to be called by the host application upon its exit.
#
# --- END OF DESCRIPTION ---

import configparser
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CallbackQueryHandler

# --- НАСТРОЙКА ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Загрузка конфигурации из файла gate_check.ini
config = configparser.ConfigParser()
config.read('gate_check.ini')
TOKEN = config['Telegram ID']['TOKEN'].strip('"')
CHAT_ID = config['Telegram ID']['chat_id'].strip('"')


# --- СОСТОЯНИЕ МОДУЛЯ ---
# Эти переменные будут хранить единственный экземпляр бота для всей сессии
_application = None
_is_initialized = False


# --- ВНУТРЕННИЕ ФУНКЦИИ МОДУЛЯ ---

async def _button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Единый обработчик кнопок. Находит соответствующий Future-объект
    в "памяти" бота и передает в него результат нажатия.
    """
    query = update.callback_query
    await query.answer()

    message_id = query.message.message_id
    if 'pending_futures' in context.bot_data and message_id in context.bot_data['pending_futures']:
        future = context.bot_data['pending_futures'].pop(message_id)
        if not future.done():
            # Передаем данные кнопки (например, '1', '2') в Future
            future.set_result(query.data)
        await query.edit_message_text(text=f"Спасибо! Ваш выбор получен.")
    else:
        # Этот запрос мог истечь по таймауту или уже был обработан
        await query.edit_message_text(text=f"Этот запрос более не активен.")


async def _initialize_bot_if_needed():
    """
    Приватная функция. Проверяет, запущен ли бот. Если нет - создает
    и запускает единственный экземпляр на все время работы программы.
    """
    global _application, _is_initialized
    if _is_initialized:
        return

    logger.info("Первый вызов. Инициализация постоянного экземпляра Telegram-бота...")
    
    # Создаем экземпляр приложения
    _application = Application.builder().token(TOKEN).build()
    
    # Добавляем единственный, постоянный обработчик кнопок
    _application.add_handler(CallbackQueryHandler(_button_callback))
    
    # Инициализируем "память" бота для хранения Future-объектов
    _application.bot_data['pending_futures'] = {}

    # Запускаем все компоненты бота (включая опрос)
    await _application.initialize()
    await _application.updater.start_polling()
    await _application.start()
    
    _is_initialized = True
    logger.info("Постоянный экземпляр Telegram-бота успешно запущен и работает в фоновом режиме.")


# --- ПУБЛИЧНЫЙ ИНТЕРФЕЙС (API) ДЛЯ ВНЕШНИХ ПРОГРАММ ---

async def send_message_with_buttons(text: str, button_names: list, time_out: int = 60) -> str:
    """
    Публичная функция, которую вызывает Online_check_gate.py.
    Ее сигнатура и поведение полностью соответствуют ожиданиям внешней программы.
    """
    # 1. Убедимся, что наш бот запущен. Если нет - эта функция его запустит.
    await _initialize_bot_if_needed()

    # 2. Основная логика отправки и ожидания
    try:
        future = asyncio.Future()
        
        keyboard = [
            # Нумеруем callback_data с 1, как ожидает ваш код
            [InlineKeyboardButton(name, callback_data=str(i + 1))] 
            for i, name in enumerate(button_names)
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Используем уже существующий _application для отправки
        message = await _application.bot.send_message(
            chat_id=CHAT_ID,
            text=text,
            reply_markup=reply_markup
        )
        
        # Сохраняем Future, чтобы _button_callback мог его найти
        _application.bot_data['pending_futures'][message.message_id] = future
        
        logger.info(f"Сообщение (ID: {message.message_id}) отправлено. Ожидание ответа {time_out} сек...")
        
        # Ждем результата от _button_callback
        result = await asyncio.wait_for(future, timeout=float(time_out))
        return result

    except asyncio.TimeoutError:
        logger.warning(f"Время ожидания ответа на сообщение истекло. Возвращаем -1.")
        # Удаляем просроченный Future из памяти
        if 'message' in locals() and message.message_id in _application.bot_data['pending_futures']:
            _application.bot_data['pending_futures'].pop(message.message_id)
        return "-1"
    except Exception as e:
        logger.error(f"Непредвиденная ошибка в send_message_with_buttons: {e}")
        return "-2"


async def cleanup_bot():
    """
    Публичная функция для остановки бота. Вызывается Online_check_gate.py при выходе.
    """
    global _application, _is_initialized
    if not _is_initialized or not _application:
        return
    
    logger.info("Получена команда на остановку постоянного экземпляра Telegram-бота...")
    if _application.updater and _application.updater.running:
        await _application.updater.stop()
    if _application.running:
        await _application.stop()
    await _application.shutdown()
    _is_initialized = False
    logger.info("Постоянный экземпляр Telegram-бота остановлен.")


# --- AUTONOMOUS TEST MODULE ---

async def main_test():
    """
    Автономная функция для тестирования функциональности этого модуля.
    Запускается только если файл выполнен напрямую (python TelegramButtonsGen.py).
    """
    print("--- Запуск автономного теста для TelegramButtonsGen.py ---")
    
    # Этот блок try...finally гарантирует, что бот будет остановлен
    # даже если во время теста произойдет ошибка.
    try:
        # Тестовый вызов основной публичной функции
        result = await send_message_with_buttons(
            text="Это тестовое сообщение. Пожалуйста, выберите опцию:",
            button_names=["Тест 1", "Тест 2", "Тест 3"],
            time_out=30  # Короткий таймаут для теста
        )
        
        print("\n" + "="*40)
        print(f"  Тестовый скрипт получил результат: '{result}'")
        print("="*40 + "\n")

    finally:
        # Убеждаемся, что бот всегда корректно останавливается после теста
        print("--- Тест завершен, очистка ресурсов бота... ---")
        await cleanup_bot()
        print("--- Очистка завершена. ---")


if __name__ == "__main__":
    print("Файл TelegramButtonsGen.py запущен в режиме автономного тестирования...")
    # asyncio.run() создает и управляет циклом событий для нашего теста
    asyncio.run(main_test())