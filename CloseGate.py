# CloseGate.py

import configparser
import asyncio
import sys
import logging
from Check_Gate_State import check_gate  # Updated import statement
from TelegramButtonsGen import send_message_with_buttons
from ControlSwitch import control_shelly_switch

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    # Read configuration
    config = configparser.ConfigParser()
    config_file = 'gate_check.ini'
    read_files = config.read(config_file)

    if not read_files:
        logger.error(f"Failed to read configuration file: {config_file}")
        sys.exit(1)

    logger.info(f"Configuration sections found: {config.sections()}")

    try:
        # Telegram configurations
        telegram_token = config['Telegram ID']['TOKEN'].strip('"')
        chat_id = config['Telegram ID']['chat_id'].strip('"')
        
        # Device configurations
        DEVICE_ID = config['Device ID']['big_gate_ID']
        ip_gate = config['Device ID']['ip_gate']
        
    except KeyError as e:
        logger.error(f"Configuration Error: Missing key {e}")
        sys.exit(1)
    
    # Check gate state
    gate_state = check_gate(DEVICE_ID)
    
    if gate_state:
        gate_closed, battery = gate_state
        gate_status = "Closed" if gate_closed else "Open"
        message = f"🚪 *Gate Status*: {gate_status}\n🔋 *Battery Level*: {battery}%"
    else:
        message = "❌ Failed to retrieve gate state."
    
    # Define buttons
    buttons = ["Open/Close gate", "Cancel"]
    
    # Send Telegram message with buttons
    logger.info("Sending Telegram message with buttons...")
    response = await send_message_with_buttons(message, buttons, time_out=60)
    
    if response == 0:
        # "Open/Close gate" pressed
        logger.info("User selected 'Open/Close gate'. Toggling the gate...")
        try:
            # Toggle the gate using ip_gate
            control_shelly_switch(ip_gate)
            logger.info("Gate toggled successfully.")
        except Exception as e:
            logger.error(f"Failed to toggle gate: {e}")
    elif response == 1:
        # "Cancel" pressed
        logger.info("User selected 'Cancel'. Terminating the application.")
    else:
        # Handle other cases, e.g., timeout or error
        logger.warning("No valid response received or an error occurred.")
    
    logger.info("Application has finished execution.")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by the user.")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
