import configparser
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import asyncio
import logging
from telegram.error import NetworkError

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def send_message_with_buttons(text: str, button_names: list, time_out: int = 0):
    # Load Telegram bot token and chat ID from the config file
    config = configparser.ConfigParser()
    config.read('gate_check.ini')
    
    TOKEN = config['Telegram ID']['TOKEN'].strip('"')
    CHAT_ID = config['Telegram ID']['chat_id'].strip('"')

    # Create the application and pass it your bot's token
    application = Application.builder().token(TOKEN).build()

    # Variable to store the button press result
    result = [-1]
    response_received = asyncio.Event()

    async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        result[0] = int(query.data)
        response_received.set()
        await update.effective_message.edit_text(f"You selected option {result[0] + 1}")

    try:
        await application.initialize()
        await application.start()

        if button_names:
            # Create the keyboard markup
            keyboard = [[InlineKeyboardButton(name, callback_data=str(i))] for i, name in enumerate(button_names)]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Add the CallbackQueryHandler
            application.add_handler(CallbackQueryHandler(button_callback))

            await application.updater.start_polling()

            message = await application.bot.send_message(chat_id=CHAT_ID, text=text, reply_markup=reply_markup)

            if time_out > 0:
                try:
                    await asyncio.wait_for(response_received.wait(), timeout=time_out)
                except asyncio.TimeoutError:
                    logger.info("Timeout reached, no button pressed")
            else:
                await response_received.wait()
        else:
            # If there are no buttons, just send the message and return immediately
            await application.bot.send_message(chat_id=CHAT_ID, text=text)
            return None

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        return -2, str(e)
    finally:
        try:
            if application.updater.running:
                await application.updater.stop()
            if application.running:
                await application.stop()
            await application.shutdown()
        except NetworkError:
            pass
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    return result[0]

# Example usage
#async def main():
#    # With buttons
#    result_with_buttons = await send_message_with_buttons(
#        "Please choose an option:",
#        ["Option 1", "Option 2", "Option 3"],
#        time_out=60
#    )
#    print(f"Result with buttons: {result_with_buttons}")
#
#    # Without buttons
#    result_without_buttons = await send_message_with_buttons(
#        "This is a message without buttons",
#        [],
#        time_out=60
#    )
#    print(f"Result without buttons: {result_without_buttons}")#
#
#if __name__ == '__main__':
#    asyncio.run(main())