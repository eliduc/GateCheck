import configparser
import subprocess
import platform
import logging
import asyncio
from TelegramButtonsGen import send_message_with_buttons
import tinytuya
from rich.console import Console
from rich.table import Table
from rich import box

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
        self.status_text = "Unknown"
        self.state = "Unknown"   # For sensors: Open/Closed
        self.battery = "Unknown" # For sensors: Battery charge percentage

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
        """Check status for Tuya sensors and retrieve their state and battery"""
        try:
            client = tinytuya.Cloud(
                apiRegion=tuya_config['API_REGION'],
                apiKey=tuya_config['ACCESS_ID'],
                apiSecret=tuya_config['ACCESS_KEY']
            )
            device_data = client.getstatus(self.address)
            if 'result' in device_data and device_data['result']:
                self.is_online = True
                # Adjust indices based on your sensor's API response
                # Example assumes:
                # result[0]['value'] -> gate_open (boolean)
                # result[1]['value'] -> battery (int)
                gate_open = device_data['result'][0].get('value', False)
                self.state = "Open" if gate_open else "Closed"
                self.battery = f"{device_data['result'][1].get('value', 0)}%"
                logging.info(f"Sensor {self.name} ({self.address}): State={self.state}, Battery={self.battery}")
                return True
            else:
                self.is_online = False
                self.state = "Unknown"
                self.battery = "Unknown"
                logging.info(f"Sensor {self.name} ({self.address}): Failed to retrieve data")
                return False
        except Exception as e:
            self.is_online = False
            self.state = "Unknown"
            self.battery = "Unknown"
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

async def send_initial_status(devices, sensors):
    """Sends the initial status of all devices via Telegram."""
    message = "📡 **Initial Device Status:**\n\n"

    if devices:
        message += "📟 **Devices (PCs/Raspberry Pis):**\n"
        for device in devices:
            identifier = device.address
            status = "Online" if device.is_online else "Offline"
            message += f"• {device.name} ({identifier}): {status}\n"
        message += "\n"

    if sensors:
        message += "🔋 **Sensors:**\n"
        for sensor in sensors:
            state = sensor.state
            battery = sensor.battery
            status = "Online" if sensor.is_online else "Offline"
            message += f"• {sensor.name}: State={state}, Battery={battery}, Status={status}\n"

    await send_message_with_buttons(text=message, button_names=[], time_out=0)

def generate_devices_table(devices):
    """Generates a rich Table object for devices (PCs/Raspberry Pis)."""
    table = Table(title="📟 Devices Online Status", box=box.SIMPLE_HEAVY)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Address", style="magenta")
    table.add_column("Type", style="green")
    table.add_column("Status", style="bold")

    for device in devices:
        if device.status_text == "Online":
            status = "[green]Online[/green]"
        elif device.status_text == "Time-out":
            status = "[brown]Time-out[/brown]"
        elif device.status_text == "N/A":
            status = "[yellow]N/A[/yellow]"
        else:
            status = "[red]Offline[/red]"

        table.add_row(device.name, device.address, device.device_type, status)

    return table

def generate_sensors_table(sensors):
    """Generates a rich Table object for sensors with colored state."""
    table = Table(title="🔋 Sensors Status", box=box.SIMPLE_HEAVY)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("State", style="magenta")
    table.add_column("Battery", style="green")
    table.add_column("Status", style="bold")

    for sensor in sensors:
        # Color the state based on its value
        if sensor.state == "Closed":
            state_display = "[green]Closed[/green]"
        elif sensor.state == "Open":
            state_display = "[red]Open[/red]"
        else:
            state_display = sensor.state  # For "Unknown" or "N/A"

        # Display battery charge only if sensor is online
        battery_display = sensor.battery if sensor.is_online else "N/A"

        if sensor.status_text == "Online":
            status = "[green]Online[/green]"
        elif sensor.status_text == "Time-out":
            status = "[brown]Time-out[/brown]"
        elif sensor.status_text == "N/A":
            status = "[yellow]N/A[/yellow]"
        else:
            status = "[red]Offline[/red]"

        table.add_row(sensor.name, state_display, battery_display, status)

    return table

def main():
    """Main function to perform a one-time device status check and display."""
    # Initialize rich console
    console = Console()

    # Load devices and configuration
    devices = load_devices(INI_FILE)
    if not devices:
        logging.error("No devices to monitor. Exiting.")
        console.print("[red]No devices to monitor. Exiting.[/red]")
        return

    delays = load_delays(INI_FILE)
    if not delays:
        logging.warning("No delay values found. Defaulting to no delays.")

    tuya_config = load_tuya_config(INI_FILE)
    if not tuya_config:
        logging.error("Failed to load Tuya configuration. Sensor monitoring will be disabled.")
        console.print("[red]Failed to load Tuya configuration. Sensor monitoring will be disabled.[/red]")
        # Mark sensors as "N/A" since Tuya config is missing
        for device in devices:
            if device.device_type == 'SENSOR':
                device.status_text = "N/A"
                device.state = "N/A"
                device.battery = "N/A"
        # Separate devices and sensors
        devices_list = [d for d in devices if d.device_type != 'SENSOR']
        sensors_list = [d for d in devices if d.device_type == 'SENSOR']
    else:
        # Perform status check
        devices_list = []
        sensors_list = []
        for device in devices:
            if device.device_type == 'SENSOR':
                device.is_online = device.check_status(tuya_config)
                device.status_text = "Online" if device.is_online else "Offline"
                sensors_list.append(device)
            else:
                device.is_online = device.check_status()
                device.status_text = "Online" if device.is_online else "Offline"
                devices_list.append(device)

    # Send initial status via Telegram
    try:
        asyncio.run(send_initial_status(devices_list, sensors_list))
    except Exception as e:
        logging.error(f"Failed to send initial Telegram message: {e}")

    # Generate and print the tables
    if devices_list:
        devices_table = generate_devices_table(devices_list)
        console.print(devices_table)
    else:
        console.print("[yellow]No PC/Raspberry Pi devices to display.[/yellow]")

    if sensors_list:
        sensors_table = generate_sensors_table(sensors_list)
        console.print(sensors_table)
    else:
        console.print("[yellow]No sensors to display.[/yellow]")

if __name__ == '__main__':
    main()
