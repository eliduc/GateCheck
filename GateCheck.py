import configparser
import asyncio
import time
import signal
from Check_Gate_State import check_gate
from ControlSwitch import control_shelly_switch
from TelegramButtonsGen import send_message_with_buttons, cleanup_bot
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("GateCheck")

# Global variable for graceful shutdown
shutdown_requested = False

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
        result = await send_message_with_buttons(message, [], 30)
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
                # Only send message when gate is actually closed after the command
                await send_message_with_buttons("The gate is closed", [], 0)
                logger.info("Gate closed successfully")
                return True
        else:
            logger.error("Failed to check gate state during closing attempt")
            # Continue checking instead of breaking
    
    # If we've reached this point, the gate didn't close within time_to_close seconds
    await send_message_with_buttons("The gate is still open", [], 0)
    logger.warning("Gate failed to close within the specified time")
    return False

async def main():
    global shutdown_requested
    logger.info("Starting Big Gate Monitor")
    try:
        config = load_config()
    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        return

    battery_alert_1_sent = False
    battery_alert_2_sent = False
    
    try:
        while not shutdown_requested:
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
                        for _ in range(config['time_polling']):
                            if shutdown_requested:
                                break
                            await asyncio.sleep(1)
                    else:
                        logger.info(f"Gate is open. Waiting for {config['time_to_close']} seconds before rechecking")
                        for _ in range(config['time_to_close']):
                            if shutdown_requested:
                                break
                            await asyncio.sleep(1)
                        
                        if shutdown_requested:
                            break
                            
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
                            # Use 120 seconds timeout as requested
                            choice = await send_message_with_buttons(message, buttons, 120)
                            logger.info(f"User choice result: {choice}")
                            
                            if choice is None or choice == "-1" or choice == "-2":
                                logger.warning("No user input received, timeout, or error. Defaulting to closing the gate.")
                                await send_message_with_buttons("No option selected, closing gate by default", [], 0)
                                choice_num = 1  # Default to "Close gate"
                            else:
                                try:
                                    choice_num = int(choice)
                                except (ValueError, TypeError):
                                    logger.warning(f"Invalid choice value: {choice}. Defaulting to closing the gate.")
                                    await send_message_with_buttons("Invalid selection, closing gate by default", [], 0)
                                    choice_num = 1
                            
                            if choice_num == 1:  # "Close gate" (first button)
                                await send_message_with_buttons("You selected: Close gate. Executing command...", [], 0)
                                gate_closed = await close_gate_and_check(config)
                                if not gate_closed:
                                    logger.info("Continuing with regular polling after failed closing attempt")
                            elif choice_num == 2:  # Wait delay_1 minutes
                                delay = config['delay_1']
                                await send_message_with_buttons(f"You selected: Wait {delay} minutes", [], 0)
                                logger.info(f"Waiting for {delay} minutes as per user choice")
                                for _ in range(delay * 60):
                                    if shutdown_requested:
                                        break
                                    await asyncio.sleep(1)
                            elif choice_num == 3:  # Wait delay_2 minutes
                                delay = config['delay_2']
                                await send_message_with_buttons(f"You selected: Wait {delay} minutes", [], 0)
                                logger.info(f"Waiting for {delay} minutes as per user choice")
                                for _ in range(delay * 60):
                                    if shutdown_requested:
                                        break
                                    await asyncio.sleep(1)
                            elif choice_num == 4:  # Wait delay_3 minutes
                                delay = config['delay_3']
                                await send_message_with_buttons(f"You selected: Wait {delay} minutes", [], 0)
                                logger.info(f"Waiting for {delay} minutes as per user choice")
                                for _ in range(delay * 60):
                                    if shutdown_requested:
                                        break
                                    await asyncio.sleep(1)
                            else:
                                logger.warning(f"Unexpected choice value: {choice_num}. Defaulting to regular polling interval.")
                                await send_message_with_buttons("Unexpected selection, continuing normal operation", [], 0)
                            
                            # Принудительно останавливаем polling после завершения взаимодействия
                            logger.info("Interaction completed, stopping telegram bot polling to save resources")
                            try:
                                await cleanup_bot()
                            except Exception as e:
                                logger.warning(f"Error during polling cleanup: {e}")
                                
                        except Exception as e:
                            logger.error(f"Failed to send gate alert or process user choice: {e}")
                            logger.info("Defaulting to closing the gate")
                            await send_message_with_buttons("Error processing selection, closing gate by default", [], 0)
                            await close_gate_and_check(config)
                            
                            # Принудительно останавливаем polling после ошибки
                            try:
                                await cleanup_bot()
                            except Exception as cleanup_e:
                                logger.warning(f"Error during cleanup after exception: {cleanup_e}")
                else:
                    logger.error(f"Unexpected result from check_gate: {result}")
                    logger.info(f"Waiting for {config['time_polling']} seconds before retrying")
                    for _ in range(config['time_polling']):
                        if shutdown_requested:
                            break
                        await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("Received cancel signal. Shutting down...")
                break
            except Exception as e:
                logger.error(f"An unexpected error occurred: {e}")
                logger.info(f"Waiting for {config['time_polling']} seconds before retrying")
                for _ in range(config['time_polling']):
                    if shutdown_requested:
                        break
                    await asyncio.sleep(1)
    finally:
        # Cleanup bot when exiting
        try:
            logger.info("Cleaning up Telegram bot...")
            await cleanup_bot()
            logger.info("Telegram bot cleanup completed")
        except Exception as e:
            logger.error(f"Error during bot cleanup: {e}")

def handle_shutdown(signum, frame):
    global shutdown_requested
    logger.info(f"Received signal {signum}. Initiating graceful shutdown...")
    shutdown_requested = True

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