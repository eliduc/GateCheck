import configparser
import asyncio
import time
import signal
from Check_Gate_State import check_gate
from ControlSwitch import control_shelly_switch
from TelegramButtonsGen import send_message_with_buttons
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_config():
    logger.info("Loading configuration from gate_check.ini")
    config = configparser.ConfigParser()
    config.read('gate_check.ini')
    
    try:
        config_dict = {
            'big_gate_ID': config['Device ID']['big_gate_ID'].strip().strip('"'),
            'time_polling': int(config['Time-outs']['time_polling']),
            'time_to_close': int(config['Time-outs']['time_to_close']),
            'close_tries': int(config['Time-outs']['close_tries']),
            'delay_1': int(config['Time-outs']['delay_1']),
            'delay_2': int(config['Time-outs']['delay_2']),
            'delay_3': int(config['Time-outs']['delay_3']),
            'battery_limit_1': int(config['Battery limits']['battery_limit_1']),
            'battery_limit_2': int(config['Battery limits']['battery_limit_2']),
            'ip_gate': config['Device ID']['ip_gate'].strip().strip('"')
        }
        
        logger.info("Configuration values:")
        for key, value in config_dict.items():
            logger.info(f"{key}: {value}")
        
        return config_dict
    except KeyError as e:
        logger.error(f"Missing configuration key: {e}")
        raise ConfigError(f"Missing required configuration key: {e}")
    except ValueError as e:
        logger.error(f"Invalid configuration value: {e}")
        raise ConfigError(f"Invalid configuration value: {e}")

class ConfigError(Exception):
    pass

async def send_battery_alert(message):
    logger.info(f"Sending battery alert: {message}")
    try:
        result = await send_message_with_buttons(message, [], 0)
        logger.info(f"Battery alert sent successfully")
    except Exception as e:
        logger.error(f"Failed to send battery alert: {e}")

async def close_gate_and_check(config):
    logger.info("Attempting to close the gate")
    control_shelly_switch(config['ip_gate'])
    
    start_time = time.time()
    while time.time() - start_time < config['time_to_close']:
        await asyncio.sleep(2)  # Poll every 2 seconds
        result = check_gate(config['big_gate_ID'])
        if result and isinstance(result, tuple) and len(result) == 2:
            gate_closed, _ = result
            if gate_closed:
                await send_message_with_buttons("The gate is closed", [], 0)
                logger.info("Gate closed successfully")
                return True
        else:
            logger.error("Failed to check gate state during closing attempt")
    
    # If we've reached this point, the gate didn't close within time_to_close seconds
    await send_message_with_buttons("The gate is still open", [], 0)
    logger.warning("Gate failed to close within the specified time")
    return False

async def main():
    logger.info("Starting Big Gate Monitor")
    try:
        config = load_config()
    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        return

    battery_alert_1_sent = False
    battery_alert_2_sent = False
    
    while True:
        try:
            logger.info("Checking gate state")
            result = check_gate(config['big_gate_ID'])
            
            logger.info(f"Raw result from check_gate: {result}")
            
            if result and isinstance(result, tuple) and len(result) == 2:
                gate_closed, battery = result
                logger.info(f"Gate state: {'Closed' if gate_closed else 'Open'}, Battery: {battery}%")
                
                # Battery checks
                if battery < config['battery_limit_2'] and not battery_alert_2_sent:
                    logger.warning(f"Critical battery level: {battery}%")
                    await send_battery_alert(f"Attention! Critical battery state of the big gate door sensor: {battery}%")
                    battery_alert_2_sent = True
                elif battery < config['battery_limit_1'] and not battery_alert_1_sent:
                    logger.warning(f"Low battery level: {battery}%")
                    await send_battery_alert(f"Attention! Big gate sensor battery is less than {config['battery_limit_1']}%")
                    battery_alert_1_sent = True
                elif battery >= config['battery_limit_1']:
                    if battery_alert_1_sent or battery_alert_2_sent:
                        logger.info("Battery level recovered")
                    battery_alert_1_sent = False
                    battery_alert_2_sent = False
                
                if gate_closed:
                    logger.info(f"Gate is closed. Waiting for {config['time_polling']} seconds before next check")
                    await asyncio.sleep(config['time_polling'])
                else:
                    logger.info(f"Gate is open. Waiting for {config['time_to_close']} seconds before rechecking")
                    await asyncio.sleep(config['time_to_close'])
                    logger.info("Rechecking gate state")
                    result = check_gate(config['big_gate_ID'])
                    if result and isinstance(result, tuple) and len(result) == 2 and result[0]:
                        logger.info("Gate is now closed. Continuing regular polling")
                        continue
                    
                    # Gate is still open
                    logger.warning("Gate is still open. Sending alert with options")
                    message = f"The big gate has been open for {config['time_to_close']} seconds!"
                    buttons = [
                        "Close gate",
                        f"Wait {config['delay_1']} minutes",
                        f"Wait {config['delay_2']} minutes",
                        f"Wait {config['delay_3']} minutes"
                    ]
                    try:
                        choice = await send_message_with_buttons(message, buttons, 0)
                        logger.info(f"User choice result: {choice}")
                        
                        if choice is None:
                            logger.warning("No user input received or message sent without buttons. Defaulting to closing the gate.")
                            choice = 0
                        
                        if choice == 0:  # "Close gate"
                            gate_closed = await close_gate_and_check(config)
                            if not gate_closed:
                                logger.info("Continuing with regular polling after failed closing attempt")
                        elif choice in [1, 2, 3]:
                            delay = config['delay_1'] if choice == 1 else (config['delay_2'] if choice == 2 else config['delay_3'])
                            logger.info(f"Waiting for {delay} minutes as per user choice")
                            await asyncio.sleep(delay * 60)  # Convert minutes to seconds
                        elif isinstance(choice, tuple) and choice[0] == -2:
                            logger.error(f"Error in sending message: {choice[1]}")
                            logger.info("Defaulting to closing the gate")
                            await close_gate_and_check(config)
                        else:
                            logger.warning(f"Unexpected choice value: {choice}. Defaulting to regular polling interval.")
                    except Exception as e:
                        logger.error(f"Failed to send gate alert or process user choice: {e}")
                        logger.info("Defaulting to closing the gate")
                        await close_gate_and_check(config)
            else:
                logger.error(f"Unexpected result from check_gate: {result}")
                logger.info(f"Waiting for {config['time_polling']} seconds before retrying")
                await asyncio.sleep(config['time_polling'])
        except asyncio.CancelledError:
            logger.info("Received cancel signal. Shutting down...")
            break
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
            logger.info(f"Waiting for {config['time_polling']} seconds before retrying")
            await asyncio.sleep(config['time_polling'])

def handle_shutdown(signum, frame):
    logger.info(f"Received signal {signum}. Initiating shutdown...")
    for task in asyncio.all_tasks():
        task.cancel()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down...")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
    finally:
        logger.info("Big Gate Monitor has shut down.")