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
    def __init__(self, name, address, device_type, online_interval, offline_interval):
        self.name = name
        self.address = address  # Can be either IP address or device ID
        self.device_type = device_type.upper()
        self.online_interval = online_interval
        self.offline_interval = offline_interval
        self.is_online = False
        self.status_label = None
        self.time_out_until = None

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
        for name, value in config.items('Computers'):
            parts = value.split()
            if len(parts) == 4:
                ip, device_type, online_interval, offline_interval = parts
                try:
                    device = Device(name, ip, device_type, 
                                  int(online_interval), int(offline_interval))
                    devices.append(device)
                except ValueError:
                    logging.error(f"Invalid intervals for device '{name}'. Skipping.")

    # Load Sensors
    if 'Sensors' in config.sections():
        for name, value in config.items('Sensors'):
            parts = value.split()
            if len(parts) == 4:
                device_id, device_type, online_interval, offline_interval = parts
                try:
                    device = Device(name, device_id, device_type,
                                  int(online_interval), int(offline_interval))
                    devices.append(device)
                except ValueError:
                    logging.error(f"Invalid intervals for sensor '{name}'. Skipping.")

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
    def __init__(self, root, devices, gui_update_queue):
        self.root = root
        self.devices = devices
        self.gui_update_queue = gui_update_queue
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
        if device.is_online:
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
        status = "Online" if device.is_online else "Offline"
        message += f"• {device.name} ({identifier}): {status}\n"
    send_telegram_message_sync(message, [], 0)

def monitor_device(device, gui_update_queue, delay_telegram, delays, tuya_config):
    """Monitor a single device's status."""
    previous_status = device.is_online
    while True:
        try:
            current_status = device.check_status(tuya_config)
            device.is_online = current_status
            logging.info(f"Device {device.name} ({device.address}) is {'Online' if current_status else 'Offline'}")

            if current_status != previous_status:
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
                    # Device went Online
                    logging.info(f"Device {device.name} is back Online.")
                    send_telegram_message_sync(f"Device {device.name} is Online.", [], 0)
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

    # Perform initial status check
    for device in devices:
        device.is_online = device.check_status(tuya_config)

    # Initialize GUI
    root = tk.Tk()
    gui = OnlineCheckGUI(root, devices, gui_update_queue)
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