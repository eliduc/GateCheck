import configparser
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk
import platform
import logging
import asyncio
from TelegramButtonsGen import send_message_with_buttons, cleanup_bot
import tinytuya
import queue
import atexit
import re
from Check_Gate_State import check_gate
from ControlSwitch import control_shelly_switch

# Define the path to the INI files
INI_FILE = 'online_check.ini'
TELEGRAM_INI_FILE = 'gate_check.ini'  # Separate INI file for Telegram

# Configure logging
logging.basicConfig(
    filename='device_status.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Global asyncio event loop for telegram operations
telegram_loop = None
telegram_thread = None

def start_telegram_loop():
    """Start the telegram event loop in a separate thread"""
    global telegram_loop
    telegram_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(telegram_loop)
    telegram_loop.run_forever()

def stop_telegram_loop():
    """Stop the telegram event loop"""
    global telegram_loop, telegram_thread
    if telegram_loop:
        # Schedule cleanup and stop
        asyncio.run_coroutine_threadsafe(cleanup_bot(), telegram_loop)
        telegram_loop.call_soon_threadsafe(telegram_loop.stop)
        if telegram_thread:
            telegram_thread.join(timeout=5)

# Register cleanup on exit
atexit.register(stop_telegram_loop)

class Device:
    def __init__(self, name, address, device_type, online_interval, offline_interval, sec_after_open=None, sec_after_close=None, attempts_after_close=None):
        self.name = name
        self.address = address  # Can be either IP address or device ID
        self.device_type = device_type.upper()
        self.online_interval = online_interval
        self.offline_interval = offline_interval
        self.is_online = False
        self.status_label = None
        self.time_out_until = None
        self.gate_state = None  # For storing gate state (open/closed)
        self.battery_level = None  # For storing battery level
        # Новые параметры для BigGate
        self.sec_after_open = sec_after_open
        self.sec_after_close = sec_after_close
        self.attempts_after_close = attempts_after_close
        # Флаг для предотвращения дублирования сообщений
        self.special_monitoring_active = False
        self.last_state_change_time = 0

    def check_status(self, tuya_config=None):
        """
        Checks device status based on device type.

        Args:
            tuya_config (dict): Configuration for Tuya API if device is a sensor

        Returns:
            bool: True if device is online, False otherwise
        """
        if self.device_type == 'SENSOR':
            return self._check_sensor_status(tuya_config)
        else:
            return self._check_ping_status()

    def _check_ping_status(self):
        """Check status for PC and RPI devices using ping"""
        try:
            # Platform-specific parameters
            if platform.system().lower() == 'windows':
                ping_cmd = ['ping', '-n', '3', '-w', '1000', self.address]
            else:
                ping_cmd = ['ping', '-c', '3', '-W', '1', self.address]

            logging.debug(f"Executing ping command: {' '.join(ping_cmd)}")
            
            # Execute ping with timeout
            result = subprocess.run(
                ping_cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                universal_newlines=True,
                timeout=10
            )
            
            output = result.stdout
            return_code = result.returncode
            
            logging.debug(f"Ping return code for {self.name}: {return_code}")
            logging.debug(f"Ping output for {self.name}:\n{output}")
            
            # Check for failure messages FIRST (before checking return code)
            failure_indicators = [
                'Destination host unreachable',
                'Destination net unreachable', 
                'Request timed out',
                'could not find host',
                'Ping request could not find',
                'transmit failed',
                'General failure',
                'No route to host'
            ]
            
            for indicator in failure_indicators:
                if indicator.lower() in output.lower():
                    logging.info(f"Ping failed for {self.name} ({self.address}): Found '{indicator}'")
                    return False
            
            # For Windows, check if we have actual successful replies
            if platform.system().lower() == 'windows':
                # Look for successful replies with TTL
                # Format: "Reply from X.X.X.X: bytes=32 time<1ms TTL=64"
                success_pattern = r'Reply from ' + re.escape(self.address) + r'.*TTL=\d+'
                success_matches = re.findall(success_pattern, output, re.IGNORECASE)
                success_count = len(success_matches)
                
                # Also check the statistics line
                stats_match = re.search(r'Received = (\d+)', output)
                if stats_match:
                    received = int(stats_match.group(1))
                    # If received > 0 but no successful replies from target IP, it's a false positive
                    if received > 0 and success_count == 0:
                        logging.info(f"Ping false positive for {self.name}: Received {received} packets but none from target IP")
                        return False
                
                # Need at least 2 successful replies from the target IP
                success = success_count >= 2
                logging.info(f"Ping {self.name} ({self.address}): {success_count}/3 successful replies, {'Online' if success else 'Offline'}")
                return success
                
            else:  # Linux/Unix
                # Linux is more straightforward - check return code and parse statistics
                if return_code != 0:
                    return False
                    
                match = re.search(r'(\d+) packets transmitted, (\d+) received', output)
                if match:
                    transmitted = int(match.group(1))
                    received = int(match.group(2))
                    success = received >= 2
                    logging.info(f"Ping {self.name} ({self.address}): {received}/{transmitted} packets, {'Success' if success else 'Failed'}")
                    return success
                else:
                    return False
            
        except subprocess.TimeoutExpired:
            logging.error(f"Ping timeout for {self.name} ({self.address})")
            return False
        except Exception as e:
            logging.error(f"Error pinging {self.address}: {e}")
            return False

    def _check_sensor_status(self, tuya_config):
        """Check status for Tuya sensors"""
        try:
            client = tinytuya.Cloud(
                apiRegion=tuya_config['API_REGION'],
                apiKey=tuya_config['ACCESS_ID'],
                apiSecret=tuya_config['ACCESS_KEY']
            )
            device_data = client.getstatus(self.address)
            success = 'result' in device_data
            
            # For biggate, also check the gate state
            if success and self.name.lower() == 'biggate':
                try:
                    gate_result = check_gate(self.address)
                    if gate_result:
                        gate_closed, battery = gate_result
                        self.gate_state = 'Closed' if gate_closed else 'Open'
                        self.battery_level = battery
                        logging.info(f"Gate {self.name} sensor check: gate_closed={gate_closed} -> gate_state='{self.gate_state}', Battery: {battery}%")
                    else:
                        self.gate_state = None
                        self.battery_level = None
                        logging.warning(f"Failed to get gate state for {self.name}")
                except Exception as e:
                    logging.error(f"Error checking gate state: {e}")
                    self.gate_state = None
                    self.battery_level = None
            
            logging.info(f"Checking sensor {self.name} ({self.address}): {'Success' if success else 'Failed'}")
            return success
        except Exception as e:
            logging.error(f"Error checking sensor {self.address}: {e}")
            return False

def load_delays(ini_file):
    """
    Loads delay_telegram and delay values from the INI configuration file.

    Args:
        ini_file (str): Path to the INI file.

    Returns:
        tuple: (delay_telegram in minutes, list of delay options in minutes)
    """
    config = configparser.ConfigParser()
    config.read(ini_file)
    delays = []
    delay_telegram = 5  # Default value if not specified
    if 'Time-outs' in config.sections():
        for key in sorted(config['Time-outs'].keys()):
            try:
                if key.lower() == 'delay_telegram':
                    delay_telegram = int(config['Time-outs'][key])
                else:
                    delay = int(config['Time-outs'][key])
                    delays.append(delay)
            except ValueError:
                logging.error(f"Invalid delay value for {key} in [Time-outs]. Skipping.")
    else:
        logging.warning("No [Time-outs] section found in the INI file.")
    return delay_telegram, delays

def load_devices(ini_file):
    """Loads both computer and sensor devices from the INI file"""
    config = configparser.ConfigParser()
    config.read(ini_file)
    devices = []

    # Load Computers
    if 'Computers' in config.sections():
        logging.info(f"Loading computers from [Computers] section...")
        for name, value in config.items('Computers'):
            logging.info(f"Processing computer: {name} = {value}")
            parts = value.split()
            if len(parts) == 4:
                ip, device_type, online_interval, offline_interval = parts
                try:
                    device = Device(name, ip, device_type, 
                                  int(online_interval), int(offline_interval))
                    devices.append(device)
                    logging.info(f"Added computer device: {name}")
                except ValueError:
                    logging.error(f"Invalid intervals for device '{name}'. Skipping.")
            else:
                logging.error(f"Invalid format for computer '{name}': expected 4 parts, got {len(parts)}")

    # Load Sensors
    if 'Sensors' in config.sections():
        logging.info(f"Loading sensors from [Sensors] section...")
        for name, value in config.items('Sensors'):
            logging.info(f"Processing sensor: {name} = {value}")
            # Skip ip_gate entry
            if name.lower() == 'ip_gate':
                logging.info(f"Skipping ip_gate entry: {name}")
                continue
            parts = value.split()
            
            # Специальная обработка для BigGate с расширенными параметрами
            if name.lower() == 'biggate' and len(parts) == 7:
                device_id, device_type, online_interval, offline_interval, sec_after_open, sec_after_close, attempts_after_close = parts
                try:
                    device = Device(name, device_id, device_type.upper(),  # Приводим к верхнему регистру
                                  int(online_interval), int(offline_interval),
                                  int(sec_after_open), int(sec_after_close), int(attempts_after_close))
                    devices.append(device)
                    logging.info(f"Added BigGate device with extended parameters: {name} - sec_after_open: {sec_after_open}, sec_after_close: {sec_after_close}, attempts: {attempts_after_close}")
                except ValueError as e:
                    logging.error(f"Invalid parameters for BigGate '{name}': {e}. Skipping.")
            elif len(parts) == 4:
                device_id, device_type, online_interval, offline_interval = parts
                try:
                    device = Device(name, device_id, device_type.upper(),  # Приводим к верхнему регистру
                                  int(online_interval), int(offline_interval))
                    devices.append(device)
                    logging.info(f"Added sensor device: {name}")
                except ValueError as e:
                    logging.error(f"Invalid intervals for sensor '{name}': {e}. Skipping.")
            else:
                logging.error(f"Invalid format for sensor '{name}': expected 4 or 7 parts (for BigGate), got {len(parts)}")
    else:
        logging.warning("No [Sensors] section found in INI file")

    logging.info(f"Total devices loaded: {len(devices)}")
    for device in devices:
        logging.info(f"Device: {device.name} ({device.device_type}) - {device.address}")
    
    return devices

def load_tuya_config(ini_file):
    """Loads Tuya API configuration from the INI file"""
    config = configparser.ConfigParser()
    config.read(ini_file)
    if 'tuya' in config.sections():
        return {
            'ACCESS_ID': config['tuya']['ACCESS_ID'].strip(),
            'ACCESS_KEY': config['tuya']['ACCESS_KEY'].strip(),
            'API_REGION': config['tuya']['API_REGION'].strip()
        }
    return None

def load_gate_ip(ini_file):
    """Load gate IP address from INI file"""
    config = configparser.ConfigParser()
    config.read(ini_file)
    if 'Sensors' in config.sections() and 'ip_gate' in config['Sensors']:
        return config['Sensors']['ip_gate'].strip()
    return None

def send_telegram_message_sync(text, button_names, time_out):
    """Synchronous wrapper for sending telegram messages"""
    global telegram_loop
    if telegram_loop:
        future = asyncio.run_coroutine_threadsafe(
            send_message_with_buttons(text, button_names, time_out),
            telegram_loop
        )
        try:
            return future.result(timeout=time_out + 10 if time_out > 0 else 30)
        except Exception as e:
            logging.error(f"Error sending telegram message: {e}")
            return -1
    return -1

class OnlineCheckGUI:
    def __init__(self, root, devices, gui_update_queue, gate_ip):
        self.root = root
        self.devices = devices
        self.gui_update_queue = gui_update_queue
        self.gate_ip = gate_ip
        self.last_gate_toggle = 0  # Время последнего нажатия кнопки
        self.root.title("Device Online Status")
        
        # Get screen dimensions
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        
        # Set window size to screen size
        self.root.geometry(f"{screen_width}x{screen_height}")
        self.root.attributes('-fullscreen', True)
        self.root.configure(bg='black')
        
        # Calculate font sizes based on screen dimensions
        # Adjusted for smoother rendering on small screens
        self.title_font_size = min(int(screen_height * 0.04), 20)
        self.header_font_size = min(int(screen_height * 0.035), 18)
        self.content_font_size = min(int(screen_height * 0.03), 16)
        
        # Define font family with antialiasing options
        if screen_height < 600:  # For small screens
            self.font_family = ('Arial', 'Helvetica', 'sans-serif')
        else:
            self.font_family = ('Helvetica', 'Arial', 'sans-serif')
        
        self.root.bind('<Escape>', lambda event: self.root.destroy())

        # Main container with proper padding
        main_container = tk.Frame(root, bg='black')
        main_container.pack(expand=True, fill='both', padx=5, pady=5)
        
        # Calculate weights for frames based on content
        computer_count = len([d for d in devices if d.device_type in ['PC', 'RPI']])
        sensor_count = len([d for d in devices if d.device_type == 'SENSOR'])
        total_count = computer_count + sensor_count
        
        if total_count > 0:
            computer_weight = max(1, int((computer_count / total_count) * 100))
            sensor_weight = max(1, int((sensor_count / total_count) * 100))
        else:
            computer_weight = 1
            sensor_weight = 1

        # Create computers frame with weight
        self.computers_frame = tk.Frame(main_container, bg='black')
        self.computers_frame.pack(expand=True, fill='both', padx=5, pady=5)
        
        # Add a separator with minimal space
        separator = ttk.Separator(main_container, orient='horizontal')
        separator.pack(fill='x', padx=5, pady=int(screen_height * 0.01))
        
        # Create sensors frame with weight
        self.sensors_frame = tk.Frame(main_container, bg='black')
        self.sensors_frame.pack(expand=True, fill='both', padx=5, pady=5)

        # Initialize the grids with different headers for each section
        self._create_section_header(self.computers_frame, "Computers and Raspberry Pis")
        self._create_grid(
            self.computers_frame, 
            [d for d in devices if d.device_type in ['PC', 'RPI']], 
            start_row=1,
            headers=['Name', 'IP/ID', 'Type', 'Status']
        )

        self._create_section_header(self.sensors_frame, "Sensors")
        self._create_grid(
            self.sensors_frame, 
            [d for d in devices if d.device_type == 'SENSOR'],
            start_row=1,
            headers=['Name', 'Device ID', 'Type', 'Status']
        )
        
        # Configure grid weights for both frames
        for frame in [self.computers_frame, self.sensors_frame]:
            for i in range(4):  # 4 columns
                frame.grid_columnconfigure(i, weight=1)
        
        # Add gate control button if gate IP is configured
        if self.gate_ip:
            self.gate_button = tk.Button(
                main_container,
                text="Open/Close Gate",
                font=(self.font_family[0], self.content_font_size, 'bold'),
                bg='orange',
                fg='white',
                command=self.toggle_gate,
                padx=20,
                pady=10
            )
            self.gate_button.pack(side=tk.BOTTOM, pady=10)
        
        # Start queue listener
        self.start_queue_listener()

    def _create_section_header(self, frame, title):
        """Creates a section header with the specified title"""
        header = tk.Label(
            frame,
            text=title,
            font=(self.font_family[0], self.title_font_size, 'bold'),
            bg='navy',
            fg='white',
            padx=5,
            pady=2
        )
        header.grid(row=0, column=0, columnspan=4, sticky='ew')

    def _create_grid(self, frame, devices, start_row, headers):
        """Creates a grid of devices in the specified frame with specified headers"""
        # Calculate cell padding based on screen size
        cell_padding_x = min(int(self.root.winfo_screenwidth() * 0.01), 10)
        cell_padding_y = min(int(self.root.winfo_screenheight() * 0.005), 5)

        # Create headers
        for col, header in enumerate(headers):
            label = tk.Label(
                frame,
                text=header,
                font=(self.font_family[0], self.header_font_size, 'bold'),
                bg='blue',
                fg='white',
                padx=cell_padding_x,
                pady=cell_padding_y,
                borderwidth=1,
                relief='ridge'
            )
            label.grid(row=start_row, column=col, sticky='nsew')

        # Create device rows
        for row, device in enumerate(devices, start=start_row + 1):
            # Name Label
            tk.Label(
                frame,
                text=device.name,
                font=(self.font_family[0], self.content_font_size),
                bg='blue',
                fg='white',
                padx=cell_padding_x,
                pady=cell_padding_y,
                borderwidth=1,
                relief='solid'
            ).grid(row=row, column=0, sticky='nsew')

            # Address Label
            tk.Label(
                frame,
                text=device.address,
                font=(self.font_family[0], self.content_font_size),
                bg='blue',
                fg='white',
                padx=cell_padding_x,
                pady=cell_padding_y,
                borderwidth=1,
                relief='solid'
            ).grid(row=row, column=1, sticky='nsew')

            # Type Label
            tk.Label(
                frame,
                text=device.device_type,
                font=(self.font_family[0], self.content_font_size),
                bg='blue',
                fg='white',
                padx=cell_padding_x,
                pady=cell_padding_y,
                borderwidth=1,
                relief='solid'
            ).grid(row=row, column=2, sticky='nsew')

            # Status Label
            status_label = tk.Label(
                frame,
                text='Unknown',
                font=(self.font_family[0], self.content_font_size, 'bold'),
                bg='gray',
                fg='white',
                padx=cell_padding_x,
                pady=cell_padding_y,
                borderwidth=1,
                relief='solid'
            )
            status_label.grid(row=row, column=3, sticky='nsew')
            device.status_label = status_label

    def update_device_status(self, device):
        """Updates the GUI with the device's current status"""
        if device.name.lower() == 'biggate' and device.is_online:
            # For biggate when online, show gate state
            if device.gate_state:
                device.status_label.config(text=device.gate_state, bg='green', fg='white')
            else:
                device.status_label.config(text='Online', bg='green', fg='white')
        elif device.is_online:
            device.status_label.config(text='Online', bg='green', fg='white')
        elif device.time_out_until:
            device.status_label.config(text='Time-out', bg='brown', fg='white')
        else:
            device.status_label.config(text='Offline', bg='red', fg='white')

    def set_time_out_status(self, device):
        device.status_label.config(text='Time-out', bg='brown', fg='white')

    def set_status_na(self, device):
        device.status_label.config(text='N/A', bg='yellow', fg='white')

    def reset_statuses_na(self):
        """Resets all devices to N/A"""
        for device in self.devices:
            self.set_status_na(device)

    def toggle_gate(self):
        """Toggle the gate open/closed"""
        if self.gate_ip:
            # Проверка защиты от частых нажатий (сокращено до 2 секунд)
            current_time = time.time()
            if current_time - self.last_gate_toggle < 2:
                remaining = 2 - (current_time - self.last_gate_toggle)
                logging.warning(f"Gate toggle blocked - wait {remaining:.1f} more seconds")
                message = f"Please wait {remaining:.1f} more seconds before next gate operation"
                send_telegram_message_sync(message, [], 0)
                return
            
            self.last_gate_toggle = current_time
            
            try:
                # Найти устройство BigGate для проверки состояния
                biggate_device = None
                for device in self.devices:
                    if device.name.lower() == 'biggate':
                        biggate_device = device
                        break
                
                # Получить текущее состояние ворот
                initial_gate_state = None
                if biggate_device:
                    biggate_device.check_status(load_tuya_config(INI_FILE))
                    initial_gate_state = biggate_device.gate_state
                    logging.info(f"BigGate initial state: {initial_gate_state}")
                
                # Execute gate toggle in a separate thread
                def toggle_thread():
                    try:
                        # Улучшенная обработка результата
                        success = control_shelly_switch(self.gate_ip)
                        if success:
                            logging.info(f"Gate toggled successfully via {self.gate_ip}")
                        else:
                            logging.warning(f"Gate toggle completed but may not have worked properly")
                            
                        # Специальная обработка для BigGate после toggle
                        if biggate_device and biggate_device.sec_after_open is not None:
                            self.handle_biggate_after_toggle(biggate_device, initial_gate_state)
                            
                    except Exception as e:
                        logging.error(f"Failed to toggle gate: {e}")
                        # Отправляем сообщение об ошибке в Telegram
                        error_message = f"Gate control error: {str(e)}"
                        send_telegram_message_sync(error_message, [], 0)
                
                thread = threading.Thread(target=toggle_thread)
                thread.daemon = True
                thread.start()
                
            except Exception as e:
                logging.error(f"Error toggling gate: {e}")
                # Сбрасываем время последнего нажатия при ошибке
                self.last_gate_toggle = 0

    def handle_biggate_after_toggle(self, biggate_device, initial_gate_state):
        """Handle BigGate monitoring after toggle based on initial state"""
        tuya_config = load_tuya_config(INI_FILE)
        
        # Устанавливаем флаг специального мониторинга
        biggate_device.special_monitoring_active = True
        logging.info("BigGate special monitoring activated - normal monitoring will not send duplicate messages")
        
        try:
            if initial_gate_state == 'Closed':
                # Ворота были закрыты, ожидаем открытия
                logging.info(f"BigGate was Closed, waiting {biggate_device.sec_after_open} seconds to check if opened")
                time.sleep(biggate_device.sec_after_open)
                
                # Проверяем состояние один раз и возвращаемся к обычному опросу
                biggate_device.check_status(tuya_config)
                self.gui_update_queue.put((biggate_device, 'Online' if biggate_device.is_online else 'Offline'))
                
                if biggate_device.gate_state:
                    message = f"BigGate checked after {biggate_device.sec_after_open} seconds: {biggate_device.gate_state}. Battery: {biggate_device.battery_level}%"
                    send_telegram_message_sync(message, [], 0)
                    logging.info(message)
                    
                    # Записываем время изменения состояния
                    biggate_device.last_state_change_time = time.time()
                    
                    # Если ворота все еще закрыты, продолжаем проверять
                    if biggate_device.gate_state == 'Closed':
                        logging.info(f"BigGate still Closed after {biggate_device.sec_after_open} seconds, continuing to monitor for opening...")
                        attempts = 0
                        max_attempts = 10  # Максимум 10 попыток по 3 секунды = 30 секунд
                        
                        while attempts < max_attempts and biggate_device.gate_state == 'Closed':
                            time.sleep(3)  # Проверяем каждые 3 секунды
                            attempts += 1
                            
                            biggate_device.check_status(tuya_config)
                            self.gui_update_queue.put((biggate_device, 'Online' if biggate_device.is_online else 'Offline'))
                            
                            logging.info(f"BigGate opening check attempt {attempts}/{max_attempts}: {biggate_device.gate_state}")
                            
                            if biggate_device.gate_state == 'Open':
                                message = f"BigGate opened after {(biggate_device.sec_after_open + attempts * 3)} seconds. Battery: {biggate_device.battery_level}%"
                                send_telegram_message_sync(message, [], 0)
                                logging.info(message)
                                # Записываем время изменения состояния
                                biggate_device.last_state_change_time = time.time()
                                return  # Ворота открылись, выходим
                        
                        # Если ворота все еще закрыты после всех попыток
                        if biggate_device.gate_state == 'Closed':
                            total_wait_time = biggate_device.sec_after_open + (max_attempts * 3)
                            message = f"BigGate still Closed after {total_wait_time} seconds - sensor may not be working properly"
                            send_telegram_message_sync(message, [], 0)
                            logging.warning(message)
                
            elif initial_gate_state == 'Open':
                # Ворота были открыты, ожидаем закрытия
                logging.info(f"BigGate was Open, monitoring closure every {biggate_device.sec_after_close} seconds for up to {biggate_device.attempts_after_close} attempts")
                
                attempts = 0
                while attempts < biggate_device.attempts_after_close:
                    time.sleep(biggate_device.sec_after_close)
                    attempts += 1
                    
                    biggate_device.check_status(tuya_config)
                    self.gui_update_queue.put((biggate_device, 'Online' if biggate_device.is_online else 'Offline'))
                    
                    logging.info(f"BigGate closure check attempt {attempts}/{biggate_device.attempts_after_close}: {biggate_device.gate_state}")
                    
                    if biggate_device.gate_state == 'Closed':
                        message = f"BigGate closed after {attempts * biggate_device.sec_after_close} seconds. Battery: {biggate_device.battery_level}%"
                        send_telegram_message_sync(message, [], 0)
                        logging.info(message)
                        logging.info("BigGate closed successfully - returning to normal monitoring")
                        # Записываем время изменения состояния
                        biggate_device.last_state_change_time = time.time()
                        return  # Ворота закрылись, выходим и возвращаемся к обычному мониторингу
                
                # Ворота все еще открыты после всех попыток
                total_wait_time = biggate_device.sec_after_close * biggate_device.attempts_after_close
                message = f"BigGate is still open for {total_wait_time} seconds after Close Gate signal"
                
                logging.warning(f"BigGate failed to close after {biggate_device.attempts_after_close} attempts ({total_wait_time} seconds)")
                
                # Отправляем сообщение и продолжаем обычный поллинг
                send_telegram_message_sync(message, [], 0)
                logging.info(f"BigGate monitoring: sending notification and returning to regular polling")
            else:
                logging.warning(f"BigGate initial state unknown: {initial_gate_state}")
                
        finally:
            # Всегда отключаем специальный мониторинг при выходе
            biggate_device.special_monitoring_active = False
            logging.info("BigGate special monitoring deactivated - normal monitoring resumed")

    def start_queue_listener(self):
        """Start a periodic check for GUI updates from the queue."""
        self.root.after(100, self.process_queue)

    def process_queue(self):
        """Process pending GUI updates."""
        while not self.gui_update_queue.empty():
            device, status = self.gui_update_queue.get()
            if status == 'Online':
                self.update_device_status(device)
            elif status == 'Offline':
                self.update_device_status(device)
            elif status == 'Time-out':
                self.set_time_out_status(device)
            elif status == 'N/A':
                self.set_status_na(device)
        self.root.after(100, self.process_queue)

def send_initial_status(devices):
    """Send initial device status to Telegram"""
    message = "Initial Device Status:\n"
    for device in devices:
        identifier = device.address
        if device.name.lower() == 'biggate' and device.is_online and device.gate_state:
            status = f"{device.gate_state} (Battery: {device.battery_level}%)"
        else:
            status = "Online" if device.is_online else "Offline"
        message += f"• {device.name} ({identifier}): {status}\n"
    send_telegram_message_sync(message, [], 0)

def monitor_device(device, gui_update_queue, delay_telegram, delays, tuya_config):
    """Monitor a single device's status."""
    previous_status = device.is_online
    previous_gate_state = device.gate_state
    while True:
        try:
            current_status = device.check_status(tuya_config)
            device.is_online = current_status
            
            # Log status with gate state for biggate
            if device.name.lower() == 'biggate' and device.is_online and device.gate_state:
                logging.info(f"Device {device.name} ({device.address}) is Online - Gate: {device.gate_state}")
            else:
                logging.info(f"Device {device.name} ({device.address}) is {'Online' if current_status else 'Offline'}")

            # Check for status changes
            status_changed = current_status != previous_status
            gate_state_changed = (device.name.lower() == 'biggate' and 
                                device.gate_state != previous_gate_state)

            # Для BigGate проверяем, не активен ли специальный мониторинг
            skip_notification = False
            if device.name.lower() == 'biggate':
                if device.special_monitoring_active:
                    logging.info(f"BigGate normal monitoring: skipping notifications - special monitoring is active")
                    skip_notification = True
                elif gate_state_changed and device.last_state_change_time > 0:
                    # Проверяем, не было ли это изменение уже обработано специальным мониторингом
                    time_since_last_change = time.time() - device.last_state_change_time
                    if time_since_last_change < 30:  # Если изменение было менее 30 секунд назад
                        logging.info(f"BigGate normal monitoring: skipping gate state notification - already handled by special monitoring {time_since_last_change:.1f} seconds ago")
                        skip_notification = True

            if (status_changed or gate_state_changed) and not skip_notification:
                if not current_status:
                    # Device went Offline
                    delay_buttons = [f"{delay} minutes" for delay in delays]
                    selected = send_telegram_message_sync(
                        f"Device {device.name} is Offline.",
                        delay_buttons,
                        delay_telegram * 60  # Set timeout based on delay_telegram
                    )
                    logging.info(f"User selection for {device.name}: {selected}")

                    if selected is None or selected == -1:
                        # User did not respond within the timeout
                        logging.info(f"No response for device {device.name}. Re-checking status.")
                        new_status = device.check_status(tuya_config)
                        device.is_online = new_status
                        logging.info(f"Re-checking device {device.name}: {'Online' if new_status else 'Offline'}")
                        gui_update_queue.put((device, 'Offline' if not new_status else 'Online'))
                        status = "Online" if new_status else "Offline"
                        status_message = f"Device {device.name} status after timeout: {status}."
                        send_telegram_message_sync(status_message, [], 0)
                    elif 0 <= selected < len(delays):
                        delay_minutes = delays[selected]
                        if delay_minutes > 0:
                            device.time_out_until = time.time() + delay_minutes * 60
                            gui_update_queue.put((device, 'Time-out'))
                            logging.info(f"Set timeout for device {device.name} for {delay_minutes} minutes.")
                else:
                    # Device went Online or gate state changed
                    if status_changed:
                        message = f"Device {device.name} is back Online."
                        if device.name.lower() == 'biggate' and device.gate_state:
                            message += f" Gate is {device.gate_state}. Battery: {device.battery_level}%"
                        logging.info(f"Normal monitoring: {message}")
                        send_telegram_message_sync(message, [], 0)
                    elif gate_state_changed and device.name.lower() == 'biggate':
                        message = f"Gate {device.name} changed to {device.gate_state}. Battery: {device.battery_level}%"
                        logging.info(f"Normal monitoring: {message}")
                        send_telegram_message_sync(message, [], 0)
                    gui_update_queue.put((device, 'Online'))

            # Handle Time-out status
            if device.time_out_until:
                remaining = device.time_out_until - time.time()
                if remaining > 0:
                    logging.info(f"Device {device.name} is in timeout for {remaining} seconds.")
                    gui_update_queue.put((device, 'Time-out'))
                    time.sleep(remaining)
                else:
                    device.time_out_until = None
                    logging.info(f"Timeout expired for device {device.name}. Re-checking status.")
                    # After timeout, re-check status
                    new_status = device.check_status(tuya_config)
                    device.is_online = new_status
                    gui_update_queue.put((device, 'Offline' if not new_status else 'Online'))
                    status = "Online" if new_status else "Offline"
                    status_message = f"Device {device.name} status after timeout: {status}."
                    send_telegram_message_sync(status_message, [], 0)

            previous_status = current_status
            previous_gate_state = device.gate_state
            interval = device.online_interval if device.is_online else device.offline_interval
            time.sleep(interval)
        except Exception as e:
            logging.error(f"Error monitoring device {device.name}: {e}")
            time.sleep(10)  # Wait before retrying in case of error

def monitor_main_device(device, gui_update_queue, delay_telegram, delays, tuya_config, devices_list):
    """Monitor the main device and handle summary when it comes back online."""
    previous_status = device.is_online
    while True:
        try:
            current_status = device.check_status(tuya_config)
            device.is_online = current_status
            logging.info(f"Main Device {device.name} ({device.address}) is {'Online' if current_status else 'Offline'}")

            if current_status != previous_status:
                if current_status:
                    # Main device transitioned to Online
                    logging.info(f"Main device {device.name} is now Online.")
                    send_telegram_message_sync(f"Main device {device.name} is now Online.", [], 0)

                    # Check and update all devices' statuses
                    status_message = "Main device is back online. Current device statuses:\n"
                    for dev in devices_list:
                        dev_status = dev.check_status(tuya_config)
                        dev.is_online = dev_status
                        gui_update_queue.put((dev, 'Offline' if not dev_status else 'Online'))
                        
                        if dev.name.lower() == 'biggate' and dev.is_online and dev.gate_state:
                            status = f"{dev.gate_state} (Battery: {dev.battery_level}%)"
                        else:
                            status = "Online" if dev.is_online else "Offline"
                        status_message += f"• {dev.name} ({dev.address}): {status}\n"

                    # Send the status message
                    send_telegram_message_sync(status_message, [], 0)
                else:
                    # Main device transitioned to Offline
                    logging.info(f"Main device {device.name} is now Offline.")
                    send_telegram_message_sync(f"Main device {device.name} is now Offline.", [], 0)
                    gui_update_queue.put((device, 'Offline'))

            previous_status = current_status
            interval = device.online_interval if device.is_online else device.offline_interval
            time.sleep(interval)
        except Exception as e:
            logging.error(f"Error monitoring main device {device.name}: {e}")
            time.sleep(10)  # Wait before retrying in case of error

def main():
    # Start telegram event loop in separate thread
    global telegram_thread
    telegram_thread = threading.Thread(target=start_telegram_loop, daemon=True)
    telegram_thread.start()
    time.sleep(1)  # Give time for loop to start

    # Initialize a thread-safe queue for GUI updates
    gui_update_queue = queue.Queue()

    # Load devices and configuration
    devices = load_devices(INI_FILE)
    if not devices:
        logging.error("No devices to monitor. Exiting.")
        print("No devices to monitor. Exiting.")
        return

    delay_telegram, delays = load_delays(INI_FILE)
    if not delays:
        logging.warning("No delay values found. Defaulting to no delays.")

    tuya_config = load_tuya_config(INI_FILE)
    if not tuya_config:
        logging.error("Failed to load Tuya configuration. Sensor monitoring will be disabled.")
        return

    # Load gate IP
    gate_ip = load_gate_ip(INI_FILE)
    if gate_ip:
        logging.info(f"Gate control IP loaded: {gate_ip}")
    else:
        logging.warning("No gate IP configured in INI file")

    # Perform initial status check
    for device in devices:
        device.is_online = device.check_status(tuya_config)

    # Initialize GUI
    root = tk.Tk()
    gui = OnlineCheckGUI(root, devices, gui_update_queue, gate_ip)
    for device in devices:
        gui.update_device_status(device)

    # Send initial status
    try:
        send_initial_status(devices)
    except Exception as e:
        logging.error(f"Failed to send initial Telegram message: {e}")

    # Identify the main device (first in the list)
    main_device = devices[0]

    # Start monitoring threads
    # Main device monitoring thread
    main_thread = threading.Thread(
        target=monitor_main_device,
        args=(main_device, gui_update_queue, delay_telegram, delays, tuya_config, devices),
        daemon=True
    )
    main_thread.start()

    # Monitoring threads for other devices
    for device in devices[1:]:
        thread = threading.Thread(
            target=monitor_device,
            args=(device, gui_update_queue, delay_telegram, delays, tuya_config),
            daemon=True
        )
        thread.start()

    # Start the GUI main loop
    root.mainloop()

if __name__ == '__main__':
    main()