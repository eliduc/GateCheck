import configparser
import uuid
import asyncio
import logging
import sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CallbackQueryHandler,
    CommandHandler,
)

# =========================
# Configuration and Logging
# =========================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =========================
# Global Variables
# =========================

pending_responses = {}

# =========================
# Callback Handlers
# =========================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button press callbacks."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    logger.info(f"Button pressed with data: {data}")
    
    try:
        unique_id, index_str = data.split(':')
        index = int(index_str)
        
        if unique_id in pending_responses:
            future, button_names = pending_responses.pop(unique_id)
            
            if 0 <= index < len(button_names):
                button_name = button_names[index]
                logger.info(f"User selected: {button_name}")
                
                # Edit the message to show the selected option
                await query.message.edit_text(f"You selected option {button_name}")
                
                # Set the result and mark the future as done
                if not future.done():
                    future.set_result(button_name)
            else:
                logger.warning("Invalid button index received.")
                await query.message.reply_text("Invalid selection.")
        else:
            logger.warning("No pending response found for this unique_id.")
            await query.message.reply_text("This button press is no longer valid.")
    except ValueError:
        logger.error("Invalid callback data format.")
        await query.message.reply_text("Invalid callback data.")

# =========================
# Command Handlers
# =========================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command by sending a message with buttons."""
    chat_id = update.effective_chat.id
    await send_message_with_buttons(
        application=context.application,
        chat_id=chat_id,
        text="Please choose an option:",
        button_names=["Option 1", "Option 2", "Option 3"],
        time_out=60  # Wait for 60 seconds
    )

# =========================
# Utility Functions
# =========================

async def send_message_with_buttons(application, chat_id: int, text: str, button_names: list, time_out: int = 0):
    """
    Sends a message with inline buttons and waits for the user's selection.

    :param application: The Telegram Application instance.
    :param chat_id: The chat ID to send the message to.
    :param text: The message text.
    :param button_names: A list of button names.
    :param time_out: Time in seconds to wait for a response. 0 means no timeout.
    :return: The name of the selected button or None if timed out.
    """
    if not button_names:
        # If there are no buttons, send the message and return immediately
        await application.bot.send_message(chat_id=chat_id, text=text)
        return None

    # Generate a unique identifier for this message
    unique_id = str(uuid.uuid4())
    logger.debug(f"Generated unique_id: {unique_id}")

    # Create an asyncio Future to wait for the response
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    # Store the future and button names in the pending_responses
    pending_responses[unique_id] = (future, button_names)
    logger.debug(f"Stored pending response for unique_id: {unique_id}")

    # Create the keyboard markup with unique_id in callback_data
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"{unique_id}:{i}")]
        for i, name in enumerate(button_names)
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send the message with buttons
    message = await application.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    logger.info("Message with buttons sent. Waiting for user response...")

    try:
        if time_out > 0:
            # Wait for the user to press a button or timeout
            selected_button = await asyncio.wait_for(future, timeout=time_out)
            logger.info(f"User selected: {selected_button}")
            return selected_button
        else:
            # Wait indefinitely for the user to press a button
            selected_button = await future
            logger.info(f"User selected: {selected_button}")
            return selected_button
    except asyncio.TimeoutError:
        logger.info("Timeout reached, no button pressed.")
        # Optionally, edit the message to indicate timeout
        await message.edit_text("Timeout reached, no option was selected.")
        # Clean up the pending response
        pending_responses.pop(unique_id, None)
        return None

# =========================
# Main Function
# =========================

async def main():
    """Main function to run the Telegram bot."""
    # Set event loop policy for Windows
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Load configuration
    config = configparser.ConfigParser()
    config.read('gate_check.ini')

    try:
        TOKEN = config['Telegram ID']['TOKEN'].strip('"')
        CHAT_ID = config['Telegram ID']['chat_id'].strip('"')
        chat_id = int(CHAT_ID)
    except KeyError as e:
        logger.error(f"Missing configuration key: {e}")
        return
    except ValueError:
        logger.error("CHAT_ID must be an integer.")
        return

    # Create the Telegram Application
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_callback))

    # Start polling
    try:
        await application.run_polling()
    except RuntimeError as e:
        logger.error(f"RuntimeError: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")

# =========================
# Entry Point
# =========================

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except RuntimeError as e:
        logger.error(f"RuntimeError: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
