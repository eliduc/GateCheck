# GateCheckSmall_HA.py - Home Assistant Version

import asyncio
import configparser
import logging
import sys
import requests
from typing import Tuple, Optional
from datetime import datetime
from TelegramButtonsGen import send_message_with_buttons, cleanup_bot

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        # You can add FileHandler here to log to a file if desired
    ],
)
logger = logging.getLogger(__name__)


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
    
    def test_connection(self) -> bool:
        """Проверка подключения к Home Assistant"""
        try:
            response = requests.get(f"{self.ha_url}/api/", headers=self.headers, timeout=self.timeout)
            return response.status_code == 200
        except Exception:
            return False


def check_gate(gate_id: str, ha_ip: str = None, ha_token: str = None) -> Optional[Tuple[bool, float]]:
    """
    Функция для проверки состояния ворот (замена для оригинальной check_gate из Tuya)
    
    Args:
        gate_id: ID ворот
        ha_ip: IP Home Assistant (если не передан, берется из конфигурации)
        ha_token: Токен HA (если не передан, берется из конфигурации)
        
    Returns:
        Tuple (gate_closed, battery_level) или None при ошибке
    """
    # Если параметры не переданы, читаем из конфигурации
    if ha_ip is None or ha_token is None:
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
    gate_closed, battery_level = sensor.get_gate_status(gate_id)
    
    if gate_closed is not None and battery_level is not None:
        return gate_closed, battery_level
    else:
        return None


class GateMonitor:
    def __init__(self, config_file='gate_check.ini'):
        self.config = configparser.ConfigParser()
        self.config.read(config_file)

        # Read Home Assistant configuration
        try:
            # Отладочная информация
            logger.info(f"Reading config file: {config_file}")
            logger.info(f"Available sections: {self.config.sections()}")
            
            if self.config.has_section('HA'):
                logger.info(f"HA section options: {self.config.options('HA')}")
            else:
                logger.error("Section [HA] not found!")
                
            self.ha_ip = self.config.get('HA', 'HA_IP').strip('"')
            self.ha_token = self.config.get('HA', 'HA_TOKEN').strip('"')
            self.small_gate_opening_entity = self.config.get('HA', 'small_gate_opening_entity').strip('"')
            logger.info(f"Using opening entity: {self.small_gate_opening_entity}")
        except (configparser.NoSectionError, configparser.NoOptionError) as e:
            logger.error(f"Configuration Error for HA section: {e}")
            sys.exit(1)

        # Read timeouts
        try:
            self.time_polling_small = self.config.getint('Time-outs', 'time_polling_small')
            self.time_to_close_small = self.config.getint('Time-outs', 'time_to_close_small')
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError) as e:
            logger.error(f"Configuration Error: {e}")
            sys.exit(1)

        # Read delays
        try:
            self.delays = [
                self.config.getint('Time-outs', 'delay_1_small'),
                self.config.getint('Time-outs', 'delay_2_small'),
                self.config.getint('Time-outs', 'delay_3_small'),
                self.config.getint('Time-outs', 'delay_4_small'),
            ]
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError) as e:
            logger.error(f"Configuration Error: {e}")
            sys.exit(1)

        # Read battery limits
        try:
            self.battery_limit_1 = self.config.getint('Battery limits', 'battery_limit_1')
            self.battery_limit_2 = self.config.getint('Battery limits', 'battery_limit_2')
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError) as e:
            logger.error(f"Configuration Error: {e}")
            sys.exit(1)

        # Initialize previous battery level
        self.previous_battery = None
        
        # Initialize Home Assistant sensor
        self.ha_sensor = HomeAssistantGateSensor(self.ha_ip, self.ha_token)
        
        # Test connection at startup
        if not self.ha_sensor.test_connection():
            logger.error(f"Failed to connect to Home Assistant at {self.ha_ip}")
            sys.exit(1)
        else:
            logger.info(f"Successfully connected to Home Assistant at {self.ha_ip}")

    async def monitor(self):
        while True:
            # Используем новую функцию check_gate с HA API
            result = check_gate(self.small_gate_opening_entity, self.ha_ip, self.ha_token)
            if result:
                gate_closed, battery = result
                logger.info(f"Gate Closed: {gate_closed}, Battery: {battery}%")

                # Check battery levels
                await self.check_battery(battery)

                if not gate_closed:
                    logger.info("Gate is open. Waiting to confirm closure...")
                    await asyncio.sleep(self.time_to_close_small)

                    result_after_wait = check_gate(self.small_gate_opening_entity, self.ha_ip, self.ha_token)
                    if result_after_wait:
                        gate_closed_after, battery_after = result_after_wait
                        logger.info(f"After waiting - Gate Closed: {gate_closed_after}, Battery: {battery_after}%")

                        # Check battery levels again
                        await self.check_battery(battery_after)

                        if not gate_closed_after:
                            # Gate still open, send Telegram message with buttons
                            message = (
                                f"The small gate has been open for {self.time_to_close_small} seconds.\n"
                                f"The battery level is {battery_after}%."
                            )
                            buttons = [
                                f"Wait for {delay} minutes" for delay in self.delays
                            ]
                            buttons.append("Continue polling")
                            response = await send_message_with_buttons(
                                text=message,
                                button_names=buttons,
                                time_out=300  # 5 minutes timeout
                            )
                            
                            # Временно останавливаем бота после получения ответа
                            try:
                                await cleanup_bot()
                                logger.info("Telegram bot temporarily stopped after receiving response.")
                            except Exception as e:
                                logger.warning(f"Error stopping bot: {e}")

                            if response is None:
                                logger.info("No response received. Continuing polling.")
                            else:
                                try:
                                    response_int = int(response)  # Convert string to int
                                    if response_int == len(buttons):  # response = 5 for "Continue polling"
                                        logger.info("User chose to continue polling.")
                                        # Continue polling immediately
                                        pass
                                    elif 1 <= response_int <= len(self.delays):
                                        # User chose to wait for a specific delay (response 1-4 maps to delays[0-3])
                                        delay_index = response_int - 1  # Convert 1-indexed to 0-indexed
                                        delay_minutes = self.delays[delay_index]
                                        logger.info(f"User chose to wait for {delay_minutes} minutes.")
                                        await asyncio.sleep(delay_minutes * 60)
                                    else:
                                        logger.warning(f"Received unexpected response: {response} (expected 1-{len(buttons)}). Continuing polling.")
                                except (ValueError, TypeError):
                                    logger.warning(f"Received non-numeric response: {response}. Continuing polling.")
                    else:
                        logger.error("Failed to read gate state after waiting.")
                # If gate is closed, continue polling
            else:
                logger.error("Failed to read gate state.")

            await asyncio.sleep(self.time_polling_small)

    async def check_battery(self, current_battery):
        if self.previous_battery is not None:
            # Check for crossing battery_limit_1
            if current_battery < self.battery_limit_1 and self.previous_battery >= self.battery_limit_1:
                message = f"Small gate sensor battery level is less than {current_battery}%."
                await send_message_with_buttons(
                    text=message,
                    button_names=[],  # No buttons
                    time_out=0  # No waiting
                )
                # Stop bot after notification
                try:
                    await cleanup_bot()
                    logger.info("Telegram bot stopped after battery notification.")
                except Exception as e:
                    logger.warning(f"Error stopping bot after battery notification: {e}")

            # Check for crossing battery_limit_2
            if current_battery < self.battery_limit_2 and self.previous_battery >= self.battery_limit_2:
                message = f"Small gate sensor battery level is less than {current_battery}%."
                await send_message_with_buttons(
                    text=message,
                    button_names=[],  # No buttons
                    time_out=0  # No waiting
                )
                # Stop bot after notification
                try:
                    await cleanup_bot()
                    logger.info("Telegram bot stopped after battery notification.")
                except Exception as e:
                    logger.warning(f"Error stopping bot after battery notification: {e}")
        self.previous_battery = current_battery

async def main():
    gate_monitor = GateMonitor()
    try:
        await gate_monitor.monitor()
    except asyncio.CancelledError:
        logger.info("Gate monitoring has been cancelled.")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
    finally:
        logger.info("Shutting down GateMonitor.")
        # Ensure Telegram bot is properly stopped
        try:
            await cleanup_bot()
            logger.info("Telegram bot cleanup completed.")
        except Exception as e:
            logger.warning(f"Error during bot cleanup: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Program interrupted by user. Exiting...")