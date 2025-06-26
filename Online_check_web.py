import configparser
import platform
import logging
import asyncio
import json
import time
import re
import requests
import tinytuya
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

# Убедитесь, что эти файлы существуют и доступны для импорта
from Check_Gate_State import check_gate
from ControlSwitch import control_shelly_switch
from TelegramButtonsGen import send_message_with_buttons, cleanup_bot

# --- Конфигурация и Глобальные переменные ---
INI_FILE = 'online_check.ini'
logging.basicConfig(
    filename='device_status.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Глобальные переменные для хранения единого состояния приложения
DEVICES = []
TUYA_CONFIG = {}
GATE_IP = None
last_gate_toggle = 0
pending_updates = {}

# --- Lifespan Manager для FastAPI ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Выполняется один раз при старте и один раз при выключении"""
    global DEVICES, TUYA_CONFIG, GATE_IP
    DEVICES = load_devices(INI_FILE)
    TUYA_CONFIG = load_tuya_config(INI_FILE)
    GATE_IP = load_gate_ip(INI_FILE)
    logging.info(f"Application startup: Loaded {len(DEVICES)} devices.")
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
        # Логика для карточки: всегда показываем простой статус Open/Closed
        if self.name.lower() == 'biggate' and self.is_online and self.gate_state:
            status_display = self.gate_state
            
        return {
            'name': self.name, 'address': self.address, 'device_type': self.device_type,
            'is_online': self.is_online, 'status_text': status_display, 'gate_state': self.gate_state,
            'battery_level': self.battery_level, 'has_extended_params': bool(self.sec_after_open is not None),
            'special_monitoring_active': self.special_monitoring_active,
            'monitoring_text': self.monitoring_text # Добавляем новое поле в ответ
        }

    async def check_status(self, tuya_config):
        if self.device_type == 'SENSOR':
            return await asyncio.to_thread(self._check_sensor_status, tuya_config)
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

    def _check_sensor_status(self, tuya_config):
        try:
            client = tinytuya.Cloud(apiRegion=tuya_config.get('API_REGION'), apiKey=tuya_config.get('ACCESS_ID'), apiSecret=tuya_config.get('ACCESS_KEY'))
            device_data = client.getstatus(self.address)
            if 'result' not in device_data: return False
            if self.name.lower() == 'biggate':
                gate_result = check_gate(self.address)
                if gate_result: self.gate_state, self.battery_level = ('Closed' if gate_result[0] else 'Open'), gate_result[1]
                else: self.gate_state = "Error"
            return True
        except Exception as e: logging.error(f"Error checking sensor {self.name}: {e}"); return False

# --- Функции Загрузки ---
def load_devices(ini_file):
    config = configparser.ConfigParser(); config.read(ini_file)
    devices_list = []
    if 'Computers' in config:
        for name, value in config['Computers'].items():
            parts = value.split(); devices_list.append(Device(name, parts[0], parts[1], int(parts[2]), int(parts[3])))
    if 'Sensors' in config:
        for name, value in config['Sensors'].items():
            if name.lower() == 'ip_gate': continue
            parts = value.split()
            if name.lower() == 'biggate' and len(parts) == 7: devices_list.append(Device(name, parts[0], parts[1], int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5]), int(parts[6])))
            elif len(parts) == 4: devices_list.append(Device(name, parts[0], parts[1], int(parts[2]), int(parts[3])))
    return devices_list

def load_tuya_config(ini_file):
    config = configparser.ConfigParser(); config.read(ini_file)
    return config['tuya'] if 'tuya' in config else {}

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
            await asyncio.to_thread(biggate_device._check_sensor_status, TUYA_CONFIG)
            
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
                except Exception as telegram_error:
                    logging.error(f"Failed to send Telegram message: {telegram_error}")
            
    except Exception as e:
        logging.error(f"Error during special monitoring for BigGate: {e}", exc_info=True)
    finally:
        biggate_device.special_monitoring_active = False
        biggate_device.monitoring_text = "" # Очищаем детальный статус
        await asyncio.to_thread(biggate_device._check_sensor_status, TUYA_CONFIG)
        pending_updates[biggate_device.name] = biggate_device.to_dict()
        logging.info(f"Special monitoring for {biggate_device.name} finished.")

async def check_and_prepare_device(device):
    try:
        device.is_online = await device.check_status(TUYA_CONFIG)
        # Устанавливаем простой статус для карточки
        if device.is_online: 
            if device.name.lower() == 'biggate' and device.gate_state:
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
            
            if pending_updates:
                for name, data in list(pending_updates.items()): yield {"event": "device_status", "data": json.dumps(data)}
                pending_updates.clear()

            tasks = [check_and_prepare_device(device) for device in DEVICES if not device.special_monitoring_active]
            for task in asyncio.as_completed(tasks):
                device_data = await task
                if device_data: yield {"event": "device_status", "data": json.dumps(device_data)}

            await asyncio.sleep(5)
    return EventSourceResponse(event_generator())

@app.post("/toggle-gate")
async def toggle_gate():
    global last_gate_toggle
    
    if not GATE_IP: raise HTTPException(404, "Gate IP not configured")
    if time.time() - last_gate_toggle < 2: raise HTTPException(429, "Please wait")
    
    biggate_device = next((d for d in DEVICES if d.name.lower() == 'biggate'), None)
    if not biggate_device: raise HTTPException(404, "BigGate device not found")
    if biggate_device.special_monitoring_active: raise HTTPException(409, "Gate is already in a toggling process.")

    try:
        biggate_device.special_monitoring_active = True
        last_gate_toggle = time.time()
        
        # Устанавливаем первоначальный детальный статус для строки под кнопкой
        biggate_device.monitoring_text = "Обработка..."
        pending_updates[biggate_device.name] = biggate_device.to_dict()

        await asyncio.to_thread(biggate_device._check_sensor_status, TUYA_CONFIG)
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
    uvicorn.run(app, host="0.0.0.0", port=8000)