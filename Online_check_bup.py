import configparser
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk
import platform
import logging
import asyncio
from TelegramButtonsGen import send_message_with_buttons
import tinytuya

# Define the path to the INI file
INI_FILE = 'online_check.ini'

# Configure logging
logging.basicConfig(
    filename='device_status.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class Device:
    def __init__(self, name, address, device_type, online_interval, offline_interval):
        self.name = name
        self.address = address  # Can be either IP address or device ID
        self.device_type = device_type.upper()
        self.online_interval = online_interval
        self.offline_interval = offline_interval
        self.is_online = False
        self.last_checked = None
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
            param = '-n' if platform.system().lower() == 'windows' else '-c'
            timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
            timeout = '1000' if platform.system().lower() == 'windows' else '1'
            
            command = ['ping', param, '3', timeout_param, timeout, self.address]
            result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            success = result.returncode == 0
            logging.info(f"Pinging {self.name} ({self.address}): {'Success' if success else 'Failed'}")
            return success
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
    Loads delay values from the INI configuration file.

    Args:
        ini_file (str): Path to the INI file.

    Returns:
        list: A list of delay values in minutes.
    """
    config = configparser.ConfigParser()
    config.read(ini_file)
    delays = []
    if 'Time-outs' in config.sections():
        for key in sorted(config['Time-outs'].keys()):
            try:
                delay = int(config['Time-outs'][key])
                delays.append(delay)
            except ValueError:
                logging.error(f"Invalid delay value for {key} in [Time-outs]. Skipping.")
    else:
        logging.warning("No [Time-outs] section found in the INI file.")
    return delays

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

class OnlineCheckGUI:
    def __init__(self, root, devices):
        self.root = root
        self.devices = devices
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
            headers=['Name', 'IP', 'Type', 'Status']
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
        """Resets all devices except the host to N/A"""
        for device in self.devices[1:]:
            self.set_status_na(device)

async def send_initial_status(devices):
    """
    Sends a Telegram message summarizing the status of all devices.

    Args:
        devices (list): List of Device objects.
    """
    message = "Initial Device Status:\n"
    for device in devices:
        identifier = device.ip if device.ip else device.device_id
        status = "Online" if device.is_online else "Offline"
        message += f"• {device.name} ({identifier}): {status}\n"
    await send_message_with_buttons(text=message, button_names=[], time_out=0)

def monitor_device(device, gui, delays, host_event, tuya_config, is_host=False):
    """Modified monitor_device function to handle both computer and sensor devices"""
    previous_status = device.is_online
    while True:
        if is_host:
            current_status = device.check_status(tuya_config)
            device.is_online = current_status
            gui.update_device_status(device)
            if current_status != previous_status:
                if current_status:
                    try:
                        asyncio.run(send_message_with_buttons(
                            text=f"Device {device.name} is Online.",
                            button_names=[],
                            time_out=0
                        ))
                    except Exception as e:
                        logging.error(f"Failed to send Telegram message: {e}")
                    host_event.set()
                else:
                    try:
                        asyncio.run(send_message_with_buttons(
                            text=f"Device {device.name} is Offline.",
                            button_names=[],
                            time_out=0
                        ))
                    except Exception as e:
                        logging.error(f"Failed to send Telegram message: {e}")
                    gui.reset_statuses_na()
                    host_event.clear()
            previous_status = current_status
            interval = device.online_interval if device.is_online else device.offline_interval
            time.sleep(interval)
            continue

        if not host_event.is_set():
            gui.set_status_na(device)
            time.sleep(5)
            continue

        if device.time_out_until:
            remaining = device.time_out_until - time.time()
            if remaining > 0:
                gui.set_time_out_status(device)
                time.sleep(remaining)
            else:
                device.time_out_until = None
                gui.update_device_status(device)

        current_status = device.check_status(tuya_config)
        device.is_online = current_status
        gui.update_device_status(device)

        if current_status != previous_status:
            if current_status:
                try:
                    asyncio.run(send_message_with_buttons(
                        text=f"Device {device.name} is Online.",
                        button_names=[],
                        time_out=0
                    ))
                except Exception as e:
                    logging.error(f"Failed to send Telegram message: {e}")
            else:
                delay_buttons = [f"Delay for {delay} minutes" for delay in delays]
                try:
                    selected = asyncio.run(send_message_with_buttons(
                        text=f"Device {device.name} is Offline.",
                        button_names=delay_buttons,
                        time_out=0
                    ))
                except Exception as e:
                    logging.error(f"Failed to send Telegram message: {e}")
                    selected = None
                if selected is not None and 0 <= selected < len(delays):
                    delay_minutes = delays[selected]
                    if delay_minutes > 0:
                        device.time_out_until = time.time() + delay_minutes * 60
                        gui.set_time_out_status(device)
        previous_status = current_status
        interval = device.online_interval if device.is_online else device.offline_interval
        time.sleep(interval)

def main():
    # Load devices and configuration
    devices = load_devices(INI_FILE)
    if not devices:
        logging.error("No devices to monitor. Exiting.")
        print("No devices to monitor. Exiting.")
        return

    delays = load_delays(INI_FILE)
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
    gui = OnlineCheckGUI(root, devices)
    for device in devices:
        gui.update_device_status(device)

    # Send initial status
    try:
        asyncio.run(send_initial_status(devices))
    except Exception as e:
        logging.error(f"Failed to send initial Telegram message: {e}")

    # Set up monitoring
    host_device = devices[0]
    host_event = threading.Event()
    
    if host_device.is_online:
        host_event.set()
    else:
        host_event.clear()

    # Start monitoring threads
    host_thread = threading.Thread(
        target=monitor_device,
        args=(host_device, gui, delays, host_event, tuya_config, True),
        daemon=True
    )
    host_thread.start()

    for device in devices[1:]:
        thread = threading.Thread(
            target=monitor_device,
            args=(device, gui, delays, host_event, tuya_config, False),
            daemon=True
        )
        thread.start()

    root.mainloop()

if __name__ == '__main__':
    main()