import configparser
import asyncio
import time
import signal
import requests
from typing import Tuple, Optional
from ControlSwitch import control_shelly_switch
from TelegramButtonsGen import send_message_with_buttons, cleanup_bot
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("GateCheck")

# Global variable for graceful shutdown
shutdown_requested = False

class HomeAssistantGateSensor:
    """Класс для работы с датчиком ворот через Home Assistant API"""
    
    def __init__(self, ha_ip: str, ha_token: str, timeout: int = 10):
        """
        Инициализация подключения к Home Assistant
        
        Args:
            ha_ip: IP адрес Home Assistant
            ha_token: Long-lived access token
            timeout: Таймаут запросов в секундах
        """
        self.ha_url = f"http://{ha_ip}:8123"
        self.headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json",
        }
        self.timeout = timeout
    
    def get_entity_state(self, entity_id: str) -> Optional[dict]:
        """Получение состояния entity"""
        try:
            import time
            timestamp = int(time.time() * 1000)
            
            headers_no_cache = self.headers.copy()
            headers_no_cache.update({
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            })
            
            response = requests.get(
                f"{self.ha_url}/api/states/{entity_id}?_={timestamp}",
                headers=headers_no_cache,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Ошибка получения данных с {entity_id}: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Ошибка подключения для {entity_id}: {e}")
            return None
    
    def get_gate_status(self, opening_entity_id: str) -> Tuple[Optional[bool], Optional[float]]:
        """
        Получение состояния датчика ворот
        
        Args:
            opening_entity_id: Полный Entity ID датчика открытия
            
        Returns:
            Tuple (gate_closed, battery_level):
            - gate_closed: True если закрыто, False если открыто, None при ошибке
            - battery_level: процент заряда батареи или None при ошибке
        """
        # Формируем entity ID батареи, заменяя "opening" на "battery" и "binary_sensor" на "sensor"
        battery_entity_id = opening_entity_id.replace("_opening", "_battery").replace("binary_sensor.", "sensor.")
        
        # Получаем состояние датчика открытия
        opening_data = self.get_entity_state(opening_entity_id)
        gate_closed = None
        
        if opening_data:
            state = opening_data.get('state', '').lower()
            if state == 'on':
                gate_closed = False  # Ворота открыты
            elif state == 'off':
                gate_closed = True   # Ворота закрыты
            else:
                logger.warning(f"Неожиданное состояние датчика {opening_entity_id}: '{state}'")
        else:
            logger.error(f"Не удалось получить состояние датчика {opening_entity_id}")
        
        # Получаем заряд батареи
        battery_data = self.get_entity_state(battery_entity_id)
        battery_level = None
        
        if battery_data:
            try:
                battery_level = float(battery_data.get('state', 0))
            except (ValueError, TypeError):
                logger.warning(f"Некорректное значение батареи для {battery_entity_id}: {battery_data.get('state')}")
        else:
            logger.error(f"Не удалось получить заряд батареи {battery_entity_id}")
        
        return gate_closed, battery_level

def check_gate(gate_entity_id: str) -> Optional[Tuple[bool, float]]:
    """
    Функция для проверки состояния ворот (замена для оригинальной check_gate из Tuya)
    
    Args:
        gate_entity_id: Entity ID датчика открытия ворот
        
    Returns:
        Tuple (gate_closed, battery_level) или None при ошибке
    """
    # Читаем конфигурацию HA
    config = configparser.ConfigParser()
    config.read('gate_check.ini')
    
    try:
        ha_ip = config.get('HA', 'HA_IP').strip('"')
        ha_token = config.get('HA', 'HA_TOKEN').strip('"')
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        logger.error(f"Ошибка конфигурации HA: {e}")
        return None
    
    # Создаем экземпляр датчика
    sensor = HomeAssistantGateSensor(ha_ip, ha_token)
    
    # Получаем состояние
    gate_closed, battery_level = sensor.get_gate_status(gate_entity_id)
    
    if gate_closed is not None and battery_level is not None:
        return gate_closed, battery_level
    else:
        return None

def load_config():
    logger.info("Loading configuration from gate_check.ini")
    config = configparser.ConfigParser()
    config.read('gate_check.ini')
    
    try:
        config_dict = {
            'big_gate_entity': config['HA']['big_gate_opening_entity'].strip().strip('"'),
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
        # Останавливаем бота после уведомления
        try:
            await cleanup_bot()
            logger.info("Telegram bot stopped after battery notification.")
        except Exception as e:
            logger.warning(f"Error stopping bot after battery notification: {e}")
    except Exception as e:
        logger.error(f"Failed to send battery alert: {e}")

async def close_gate_and_check(config):
    logger.info("Attempting to close the gate")
    control_shelly_switch(config['ip_gate'])
    
    start_time = time.time()
    while time.time() - start_time < config['time_to_close']:
        await asyncio.sleep(2)  # Poll every 2 seconds
        result = check_gate(config['big_gate_entity'])  # Используем entity ID вместо big_gate_ID
        if result and isinstance(result, tuple) and len(result) == 2:
            gate_closed, _ = result
            if gate_closed:
                # Only send message when gate is actually closed after the command
                await send_message_with_buttons("The gate is closed", [], 0)
                logger.info("Gate closed successfully")
                # Останавливаем бота после уведомления
                try:
                    await cleanup_bot()
                    logger.info("Telegram bot stopped after gate closed notification.")
                except Exception as e:
                    logger.warning(f"Error stopping bot: {e}")
                return True
        else:
            logger.error("Failed to check gate state during closing attempt")
            # Continue checking instead of breaking
    
    # If we've reached this point, the gate didn't close within time_to_close seconds
    await send_message_with_buttons("The gate is still open", [], 0)
    logger.warning("Gate failed to close within the specified time")
    # Останавливаем бота после уведомления
    try:
        await cleanup_bot()
        logger.info("Telegram bot stopped after gate still open notification.")
    except Exception as e:
        logger.warning(f"Error stopping bot: {e}")
    return False

async def main():
    global shutdown_requested
    logger.info("Starting Big Gate Monitor (Home Assistant Version)")
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
                result = check_gate(config['big_gate_entity'])  # Используем entity ID
                
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
                        result = check_gate(config['big_gate_entity'])
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
                            f"Wait {config['delay_3']} minutes",
                            "Continue polling"
                        ]
                        try:
                            # Use 120 seconds timeout as requested
                            choice = await send_message_with_buttons(message, buttons, 120)
                            logger.info(f"User choice result: {choice}")
                            
                            # Останавливаем бота после получения ответа
                            try:
                                await cleanup_bot()
                                logger.info("Telegram bot stopped after receiving user choice.")
                            except Exception as e:
                                logger.warning(f"Error stopping bot: {e}")
                            
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
                                # Останавливаем бота после уведомления
                                try:
                                    await cleanup_bot()
                                    logger.info("Telegram bot stopped after wait notification.")
                                except Exception as e:
                                    logger.warning(f"Error stopping bot: {e}")
                                for _ in range(delay * 60):
                                    if shutdown_requested:
                                        break
                                    await asyncio.sleep(1)
                            elif choice_num == 3:  # Wait delay_2 minutes
                                delay = config['delay_2']
                                await send_message_with_buttons(f"You selected: Wait {delay} minutes", [], 0)
                                logger.info(f"Waiting for {delay} minutes as per user choice")
                                # Останавливаем бота после уведомления
                                try:
                                    await cleanup_bot()
                                    logger.info("Telegram bot stopped after wait notification.")
                                except Exception as e:
                                    logger.warning(f"Error stopping bot: {e}")
                                for _ in range(delay * 60):
                                    if shutdown_requested:
                                        break
                                    await asyncio.sleep(1)
                            elif choice_num == 4:  # Wait delay_3 minutes
                                delay = config['delay_3']
                                await send_message_with_buttons(f"You selected: Wait {delay} minutes", [], 0)
                                logger.info(f"Waiting for {delay} minutes as per user choice")
                                # Останавливаем бота после уведомления
                                try:
                                    await cleanup_bot()
                                    logger.info("Telegram bot stopped after wait notification.")
                                except Exception as e:
                                    logger.warning(f"Error stopping bot: {e}")
                                for _ in range(delay * 60):
                                    if shutdown_requested:
                                        break
                                    await asyncio.sleep(1)
                            elif choice_num == 5:  # Continue polling
                                await send_message_with_buttons("You selected: Continue polling. Resuming normal operation.", [], 0)
                                logger.info("User chose to continue polling. Resuming normal monitoring cycle.")
                                # Останавливаем бота после уведомления
                                try:
                                    await cleanup_bot()
                                    logger.info("Telegram bot stopped after continue polling notification.")
                                except Exception as e:
                                    logger.warning(f"Error stopping bot: {e}")
                                # Continue with regular polling (no additional wait)
                            else:
                                logger.warning(f"Unexpected choice value: {choice_num}. Defaulting to regular polling interval.")
                                await send_message_with_buttons("Unexpected selection, continuing normal operation", [], 0)
                                # Останавливаем бота после уведомления
                                try:
                                    await cleanup_bot()
                                    logger.info("Telegram bot stopped after unexpected choice notification.")
                                except Exception as e:
                                    logger.warning(f"Error stopping bot: {e}")
                                
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