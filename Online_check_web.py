import configparser
import platform
import logging
import asyncio
import json
import time
import re
import requests
from typing import Tuple, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

# Убедитесь, что эти файлы существуют и доступны для импорта
from ControlSwitch import control_shelly_switch
from TelegramButtonsGen import send_message_with_buttons, cleanup_bot

# --- Конфигурация и Глобальные переменные ---
INI_FILE = 'online_check.ini'

# Настройка логирования без цветов в консоли
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler('device_status.log'),
        logging.StreamHandler()
    ]
)

# Убираем цветные эмодзи из отладочных сообщений
def simple_print(text):
    """Простой вывод без эмодзи и цветов"""
    print(text)

# Глобальные переменные для хранения единого состояния приложения
DEVICES = []
HA_CONFIG = {}
GATE_IP = None
last_gate_toggle = 0
pending_updates = {}

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
                logging.error(f"Ошибка получения данных с {entity_id}: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            logging.error(f"Ошибка подключения для {entity_id}: {e}")
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
                logging.warning(f"Неожиданное состояние датчика {opening_entity_id}: '{state}'")
        else:
            logging.error(f"Не удалось получить состояние датчика {opening_entity_id}")
        
        # Получаем заряд батареи
        battery_data = self.get_entity_state(battery_entity_id)
        battery_level = None
        
        if battery_data:
            try:
                battery_level = float(battery_data.get('state', 0))
            except (ValueError, TypeError):
                logging.warning(f"Некорректное значение батареи для {battery_entity_id}: {battery_data.get('state')}")
        else:
            logging.error(f"Не удалось получить заряд батареи {battery_entity_id}")
        
        return gate_closed, battery_level

def check_gate(gate_entity_id: str) -> Optional[Tuple[bool, float]]:
    """
    Функция для проверки состояния ворот через Home Assistant
    
    Args:
        gate_entity_id: Entity ID датчика открытия ворот
        
    Returns:
        Tuple (gate_closed, battery_level) или None при ошибке
    """
    global HA_CONFIG
    
    try:
        # Исправляем чтение параметров - они приходят в нижнем регистре
        ha_ip = HA_CONFIG.get('ha_ip', '').strip('"')
        ha_token = HA_CONFIG.get('ha_token', '').strip('"')
        
        if not ha_ip or not ha_token:
            logging.error(f"HA_IP или HA_TOKEN не настроены. ha_ip='{ha_ip}', ha_token существует: {bool(ha_token)}")
            return None
            
        # Создаем экземпляр датчика
        sensor = HomeAssistantGateSensor(ha_ip, ha_token)
        
        # Получаем состояние
        gate_closed, battery_level = sensor.get_gate_status(gate_entity_id)
        
        if gate_closed is not None and battery_level is not None:
            return gate_closed, battery_level
        else:
            return None
            
    except Exception as e:
        logging.error(f"Ошибка в check_gate: {e}")
        return None

# --- Lifespan Manager для FastAPI ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Выполняется один раз при старте и один раз при выключении"""
    global DEVICES, HA_CONFIG, GATE_IP
    DEVICES = load_devices(INI_FILE)
    HA_CONFIG = load_ha_config(INI_FILE)
    GATE_IP = load_gate_ip(INI_FILE)
    logging.info(f"Application startup: Loaded {len(DEVICES)} devices with HA config.")
    yield
    await cleanup_bot()
    logging.info("Application shutdown.")

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


# --- Класс Устройства ---
class Device:
    def __init__(self, name, address, device_type, online_interval, offline_interval, 
                 sec_after_open=None, sec_after_close=None, attempts_after_close=None):
        self.name = name; self.address = address
        self.device_type = device_type.upper()
        self.is_online = False; self.status_text = "Unknown"
        self.gate_state = None; self.battery_level = None
        self.sec_after_open = sec_after_open; self.sec_after_close = sec_after_close
        self.attempts_after_close = attempts_after_close
        self.special_monitoring_active = False
        self.monitoring_text = ""  # Поле для детального статуса ПОД кнопкой

    def to_dict(self):
        status_display = self.status_text
        # Логика для карточки: всегда показываем простой статус Open/Closed для всех ворот
        if self.name.lower() in ['biggate', 'smallgate'] and self.is_online and self.gate_state:
            status_display = self.gate_state
            
        return {
            'name': self.name, 'address': self.address, 'device_type': self.device_type,
            'is_online': self.is_online, 'status_text': status_display, 'gate_state': self.gate_state,
            'battery_level': self.battery_level, 'has_extended_params': bool(self.sec_after_open is not None),
            'special_monitoring_active': self.special_monitoring_active,
            'monitoring_text': self.monitoring_text, # Добавляем новое поле в ответ
            'is_gate': self.name.lower() in ['biggate', 'smallgate'],  # Флаг для фронтенда
            'gate_priority': 1 if self.name.lower() == 'biggate' else 2 if self.name.lower() == 'smallgate' else 999  # Для сортировки
        }

    async def check_status(self, ha_config):
        if self.device_type == 'SENSOR':
            return await asyncio.to_thread(self._check_sensor_status, ha_config)
        else:
            return await self._check_ping_status()

    async def _check_ping_status(self):
        try:
            cmd = ['ping', '-n' if platform.system().lower() == 'windows' else '-c', '3', '-w' if platform.system().lower() == 'windows' else '-W', '1000' if platform.system().lower() == 'windows' else '1', self.address]
            process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            output = stdout.decode('utf-8', errors='ignore')
            if process.returncode != 0 or 'unreachable' in output.lower() or 'timed out' in output.lower(): return False
            if platform.system().lower() == 'windows': return len(re.findall(r'Reply from ' + re.escape(self.address), output, re.IGNORECASE)) >= 2
            else:
                match = re.search(r'(\d+) packets transmitted, (\d+) received', output)
                return match and int(match.group(2)) >= 2
        except asyncio.TimeoutError: logging.error(f"Async ping timeout for {self.name}"); return False
        except Exception as e: logging.error(f"Error async pinging {self.name}: {e}"); return False

    def _check_sensor_status(self, ha_config):
        try:
            if self.name.lower() == 'biggate':
                # Для biggate используем entity ID из HA конфигурации
                gate_entity_id = ha_config.get('big_gate_opening_entity', '').strip('"')
                if not gate_entity_id:
                    logging.error(f"big_gate_opening_entity не настроен в конфигурации HA")
                    return False
                    
                gate_result = check_gate(gate_entity_id)
                if gate_result: 
                    self.gate_state, self.battery_level = ('Closed' if gate_result[0] else 'Open'), gate_result[1]
                    return True
                else: 
                    self.gate_state = "Error"
                    return False
            elif self.name.lower() == 'smallgate':
                # Для smallgate используем entity ID из HA конфигурации
                gate_entity_id = ha_config.get('small_gate_opening_entity', '').strip('"')
                if not gate_entity_id:
                    logging.error(f"small_gate_opening_entity не настроен в конфигурации HA")
                    return False
                    
                gate_result = check_gate(gate_entity_id)
                if gate_result: 
                    self.gate_state, self.battery_level = ('Closed' if gate_result[0] else 'Open'), gate_result[1]
                    return True
                else: 
                    self.gate_state = "Error"
                    return False
            else:
                # Для других сенсоров можно добавить поддержку по аналогии
                logging.warning(f"HA support for sensor {self.name} not implemented yet")
                return False
        except Exception as e: 
            logging.error(f"Error checking HA sensor {self.name}: {e}")
            return False

# --- Функции Загрузки ---
def load_devices(ini_file):
    config = configparser.ConfigParser()
    # Сохраняем оригинальный регистр ключей
    config.optionxform = str
    config.read(ini_file)
    devices_list = []
    if 'Computers' in config:
        for name, value in config['Computers'].items():
            parts = value.split(); devices_list.append(Device(name, parts[0], parts[1], int(parts[2]), int(parts[3])))
    if 'Sensors' in config:
        for name, value in config['Sensors'].items():
            if name.lower() == 'ip_gate': continue
            parts = value.split()
            # Для biggate и smallgate читаем entity ID из HA конфигурации, но сохраняем параметры тайминга
            if name.lower() in ['biggate', 'smallgate'] and len(parts) >= 4:
                # Используем dummy address, так как реальный entity ID будет из HA секции
                if len(parts) == 7:
                    devices_list.append(Device(name, "HA_ENTITY", parts[1], int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5]), int(parts[6])))
                else:
                    devices_list.append(Device(name, "HA_ENTITY", parts[1], int(parts[2]), int(parts[3])))
            elif len(parts) == 4: 
                devices_list.append(Device(name, parts[0], parts[1], int(parts[2]), int(parts[3])))
    return devices_list

def load_ha_config(ini_file):
    config = configparser.ConfigParser(); 
    config.read(ini_file)
    
    # Отладочная информация без эмодзи
    simple_print(f"Reading config file: {ini_file}")
    simple_print(f"Available sections: {config.sections()}")
    
    if 'HA' in config:
        ha_dict = dict(config['HA'])
        simple_print(f"HA section options: {list(ha_dict.keys())}")
        simple_print(f"HA_IP: {ha_dict.get('ha_ip', 'NOT FOUND')}")
        simple_print(f"HA_TOKEN: {'***' if ha_dict.get('ha_token') else 'NOT FOUND'}")
        simple_print(f"big_gate_opening_entity: {ha_dict.get('big_gate_opening_entity', 'NOT FOUND')}")
        simple_print(f"small_gate_opening_entity: {ha_dict.get('small_gate_opening_entity', 'NOT FOUND')}")
        return ha_dict
    else:
        simple_print("ERROR: Section [HA] not found in config file!")
        return {}

def load_gate_ip(ini_file):
    config = configparser.ConfigParser(); config.read(ini_file)
    return config.get('Sensors', 'ip_gate', fallback=None)

# --- Логика Приложения ---

async def handle_biggate_after_toggle(biggate_device, initial_gate_state):
    global pending_updates
    
    try:
        target_state = 'Open' if initial_gate_state == 'Closed' else 'Closed'
        wait_seconds = biggate_device.sec_after_open if target_state == 'Open' else biggate_device.sec_after_close
        attempts = biggate_device.attempts_after_close or 10
        
        logging.info(f"Monitoring for BigGate to become '{target_state}' for {attempts} attempts.")
        
        for i in range(attempts):
            await asyncio.sleep(wait_seconds)
            await asyncio.to_thread(biggate_device._check_sensor_status, HA_CONFIG)
            
            if biggate_device.gate_state == target_state:
                logging.info(f"BigGate reached target state '{target_state}'.")
                break
            
            # Устанавливаем детальный текст для строки под кнопкой
            progress_text = f"Ожидание: {i+1}/{attempts}"
            if target_state == 'Closed' and biggate_device.gate_state == 'Open':
                elapsed_time = (i + 1) * wait_seconds
                progress_text = f"Big Gate open for... {elapsed_time} seconds"

            biggate_device.monitoring_text = progress_text
            pending_updates[biggate_device.name] = biggate_device.to_dict()
            logging.info(f"Attempt {i+1}/{attempts}: BigGate state is still '{biggate_device.gate_state}'")
        
        if biggate_device.gate_state != target_state:
            logging.warning(f"BigGate did not reach target state '{target_state}' after all attempts.")
            
            if target_state == 'Closed' and biggate_device.gate_state == 'Open':
                total_time_open = attempts * wait_seconds
                message = f"After Gate Open/Close command the gate is still open after {total_time_open} seconds"
                logging.info(f"Sending Telegram alert: {message}")
                try:
                    await send_message_with_buttons(text=message, button_names=[], time_out=0)
                    # Останавливаем бота после уведомления
                    try:
                        await cleanup_bot()
                        logging.info("Telegram bot stopped after gate alert.")
                    except Exception as e:
                        logging.warning(f"Error stopping bot after alert: {e}")
                except Exception as telegram_error:
                    logging.error(f"Failed to send Telegram message: {telegram_error}")
            
    except Exception as e:
        logging.error(f"Error during special monitoring for BigGate: {e}", exc_info=True)
    finally:
        biggate_device.special_monitoring_active = False
        biggate_device.monitoring_text = "" # Очищаем детальный статус
        await asyncio.to_thread(biggate_device._check_sensor_status, HA_CONFIG)
        pending_updates[biggate_device.name] = biggate_device.to_dict()
        logging.info(f"Special monitoring for {biggate_device.name} finished.")

async def check_and_prepare_device(device):
    try:
        device.is_online = await device.check_status(HA_CONFIG)
        # Устанавливаем простой статус для карточки
        if device.is_online: 
            if device.name.lower() in ['biggate', 'smallgate'] and device.gate_state:
                device.status_text = device.gate_state
            else:
                 device.status_text = "Online"
        else: 
            device.status_text = "Offline"
    except Exception as e:
        logging.error(f"Error in check_and_prepare_device for {device.name}: {e}")
        device.is_online = False; device.status_text = "Error"
    return device.to_dict()

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("status.html", {"request": request, "gate_control_available": bool(GATE_IP)})

@app.get("/status-stream")
async def status_stream(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected(): break
            
            # Отправляем pending updates (с приоритетом для ворот)
            if pending_updates:
                # Сначала отправляем ворота (с сортировкой)
                gate_updates = {}
                other_updates = {}
                
                for name, data in pending_updates.items():
                    if data.get('is_gate'):
                        gate_updates[name] = data
                    else:
                        other_updates[name] = data
                
                # Сортируем ворота по приоритету
                sorted_gates = sorted(gate_updates.items(), key=lambda x: x[1].get('gate_priority', 999))
                
                # Отправляем в порядке: сначала ворота, потом остальные
                for name, data in sorted_gates:
                    yield {"event": "device_status", "data": json.dumps(data)}
                
                for name, data in other_updates.items():
                    yield {"event": "device_status", "data": json.dumps(data)}
                    
                pending_updates.clear()

            # ИЗМЕНЕНО: Отправляем данные по мере получения, а не ждем все устройства
            tasks = [check_and_prepare_device(device) for device in DEVICES if not device.special_monitoring_active]
            
            # Обрабатываем результаты по мере их поступления
            for task in asyncio.as_completed(tasks):
                device_data = await task
                if device_data: 
                    # Отправляем данные немедленно, как только получили
                    yield {"event": "device_status", "data": json.dumps(device_data)}

            await asyncio.sleep(5)
    return EventSourceResponse(event_generator())

@app.post("/toggle-gate")
async def toggle_gate():
    global last_gate_toggle
    
    if not GATE_IP: raise HTTPException(404, "Gate IP not configured")
    if time.time() - last_gate_toggle < 2: raise HTTPException(429, "Please wait")
    
    # Ищем BigGate устройство (учитываем что имя может быть в разных регистрах)
    biggate_device = None
    for d in DEVICES:
        if d.name.lower() == 'biggate':
            biggate_device = d
            break
    
    if not biggate_device: raise HTTPException(404, "BigGate device not found")
    if biggate_device.special_monitoring_active: raise HTTPException(409, "Gate is already in a toggling process.")

    try:
        biggate_device.special_monitoring_active = True
        last_gate_toggle = time.time()
        
        # Устанавливаем первоначальный детальный статус для строки под кнопкой
        biggate_device.monitoring_text = "Обработка..."
        pending_updates[biggate_device.name] = biggate_device.to_dict()

        await asyncio.to_thread(biggate_device._check_sensor_status, HA_CONFIG)
        initial_state = biggate_device.gate_state
        
        success = await asyncio.to_thread(control_shelly_switch, GATE_IP)
        
        if success:
            logging.info(f"Gate toggle successful. Initial state was {initial_state}.")
            asyncio.create_task(handle_biggate_after_toggle(biggate_device, initial_state))
            # Убираем сообщение об успехе отсюда, т.к. статус будет приходить по SSE
            return JSONResponse({"status": "success"})
        else:
            biggate_device.special_monitoring_active = False
            raise HTTPException(500, "Gate toggle command failed.")
            
    except Exception as e:
        biggate_device.special_monitoring_active = False
        logging.error(f"Failed to toggle gate: {e}", exc_info=True)
        raise HTTPException(500, f"Gate control error: {e}")

if __name__ == "__main__":
    import uvicorn
    
    # Настройка uvicorn без цветов в логах
    uvicorn_config = uvicorn.Config(
        app, 
        host="0.0.0.0", 
        port=8000,
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                },
            },
            "handlers": {
                "default": {
                    "formatter": "default",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {
                "level": "INFO",
                "handlers": ["default"],
            },
            "loggers": {
                "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
                "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
                "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
            },
        }
    )
    
    server = uvicorn.Server(uvicorn_config)
    server.run()