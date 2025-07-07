import configparser
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import asyncio
import logging
from telegram.error import NetworkError
from telegram.constants import ParseMode

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def style_text(text):
    # Use markdown to make text bold
    return f'*{text}*'

def style_button(text, color):
    color_emoji = {
        'red': '🔴',
        'blue': '🔵',
        'green': '🟢',
        'yellow': '🟡',
        'orange': '🟠',
        'purple': '🟣',
        'black': '⚫',
        'white': '⚪'
    }
    emoji = color_emoji.get(color.lower(), '⚪')  # Default to white if color not found
    return f"{emoji} {text}"

async def send_message_with_styled_buttons(text: str, button_names: list, time_out: int = 0, button_colors: list = None):
    config = configparser.ConfigParser()
    config.read('gate_check.ini')
    
    TOKEN = config['Telegram ID']['TOKEN'].strip('"')
    CHAT_ID = config['Telegram ID']['chat_id'].strip('"')

    application = Application.builder().token(TOKEN).build()

    keyboard = []
    for i, name in enumerate(button_names):
        color = button_colors[i] if button_colors and i < len(button_colors) else None
        button_text = style_button(name, color) if color else name
        keyboard.append([InlineKeyboardButton(button_text, callback_data=str(i))])
    reply_markup = InlineKeyboardMarkup(keyboard)

    result = [-1]
    response_received = asyncio.Event()

    async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        result[0] = int(query.data)
        response_received.set()
        selected_text = style_text(f"You selected {button_names[result[0]]}")
        await update.effective_message.edit_text(selected_text, parse_mode=ParseMode.MARKDOWN_V2)

    application.add_handler(CallbackQueryHandler(button_callback))

    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()

        styled_text = style_text(text)
        
        message = await application.bot.send_message(
            chat_id=CHAT_ID, 
            text=styled_text, 
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )

        if time_out > 0:
            try:
                await asyncio.wait_for(response_received.wait(), timeout=time_out)
            except asyncio.TimeoutError:
                logger.info("Timeout reached, no button pressed")
        else:
            await response_received.wait()

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
async def main():
    result = await send_message_with_styled_buttons(
        "Please choose an option:",
        ["Option 1", "Option 2", "Option 3"],
        time_out=60,
        button_colors=["red", "green", "blue"]
    )
    print(f"Result: {result}")

if __name__ == '__main__':
    asyncio.run(main())