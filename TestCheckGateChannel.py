import asyncio
from telegram import Bot
from telegram.error import TelegramError

async def send_telegram_message(token, chat_id, message):
    """
    Asynchronously sends a message to a specified Telegram chat using python-telegram-bot.

    :param token: Bot API token provided by BotFather
    :param chat_id: ID of the target chat (user or group)
    :param message: Text message to send
    :return: True if sent successfully, False otherwise
    """
    bot = Bot(token=token)
    try:
        await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
        return True
    except TelegramError as e:
        print(f"Error sending message: {e}")
        return False

if __name__ == "__main__":
    BOT_TOKEN = '8163246799:AAGovrIUQh6N9ckRA0kjiDEQ2x2IUUEZqyA'      # Replace with your bot's token
    CHAT_ID = '247210926'          # Replace with your chat ID
    MESSAGE = 'Hello from python-telegram-bot (async)! 🚀'

    async def main():
        success = await send_telegram_message(BOT_TOKEN, CHAT_ID, MESSAGE)
        if success:
            print("Message sent successfully!")
        else:
            print("Failed to send message.")

    asyncio.run(main())
