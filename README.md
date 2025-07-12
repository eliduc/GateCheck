# GateCheck - Automated Gate Monitoring System (Home Assistant Edition)

## 🚪 Description
Automated IoT system for monitoring and controlling gates using Home Assistant sensors, Shelly switches, and Telegram notifications with real-time battery monitoring. **Now fully migrated from Tuya Cloud to local Home Assistant for improved reliability and speed.**

## ✨ Features
- **Real-time gate monitoring** using Home Assistant binary sensors
- **Automatic gate control** via Shelly 1 Plus switches
- **Telegram notifications** with interactive buttons
- **Battery level monitoring** with configurable alerts
- **Web interface** with real-time updates and mobile support
- **Configurable timeouts** and retry logic
- **Async operation** for responsive monitoring
- **Local operation** - no dependency on cloud services

## 🛠️ Requirements
- Python 3.7+
- Home Assistant instance with configured gate sensors
- Telegram Bot (created via @BotFather)
- Shelly 1 Plus device for gate control (big gate only)
- Compatible gate position sensors (Xiaomi Aqara door sensors recommended)

## 📦 Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/eliduc/GateCheck.git
   cd GateCheck
   ```

2. **Install dependencies:**
   ```bash
   pip install requests python-telegram-bot fastapi uvicorn jinja2 sse-starlette
   ```

3. **Setup configuration files:**
   Create and configure the following files:
   - `gate_check.ini` - for gate monitoring programs
   - `online_check.ini` - for web interface

## ⚙️ Configuration Files

### gate_check.ini (for GateCheck.py and GateCheckSmall.py)
```ini
[Telegram ID]
TOKEN = "your_telegram_bot_token"
chat_id = "your_chat_id"

[HA]
HA_IP = "192.168.1.100"
HA_TOKEN = "your_home_assistant_long_lived_token"
big_gate_opening_entity = "binary_sensor.big_gate_sensor_opening"
small_gate_opening_entity = "binary_sensor.small_gate_sensor_opening"

[Device ID]
ip_gate = 192.168.1.200  # IP address of Shelly relay

[Time-outs]
# Big gate settings
time_polling = 180
time_to_close = 120
close_tries = 3
delay_1 = 5
delay_2 = 15
delay_3 = 30

# Small gate settings
time_polling_small = 20
time_to_close_small = 10
delay_1_small = 1
delay_2_small = 5
delay_3_small = 15
delay_4_small = 60

[Battery limits]
battery_limit_1 = 15
battery_limit_2 = 5
```

### online_check.ini (for Online_check_web.py)
```ini
[Computers]
Server = 192.168.1.100 RPI 30 10
HomeAssistant = 192.168.1.100 RPI 30 10
# Add other network devices to monitor

[Sensors]
BigGate = DUMMY SENSOR 180 120 5 10 10
SmallGate = DUMMY SENSOR 180 120
ip_gate = 192.168.1.200

[HA]
HA_IP = "192.168.1.100"
HA_TOKEN = "your_home_assistant_long_lived_token"
big_gate_opening_entity = "binary_sensor.big_gate_sensor_opening"
small_gate_opening_entity = "binary_sensor.small_gate_sensor_opening"

[Telegram ID]
TOKEN = "your_telegram_bot_token"
chat_id = "your_chat_id"

[Time-outs]
delay_1 = 0
delay_2 = 1
delay_3 = 5
delay_4 = 60
```

## 🚀 Usage

### Run Individual Programs:

**Big gate monitoring with control:**
```bash
python GateCheck.py
```

**Small gate monitoring (read-only):**
```bash
python GateCheckSmall.py
```

**Web interface (all devices):**
```bash
python Online_check_web.py
```
Access web interface at: `http://YOUR_IP:8000`

**Note:** All programs can run simultaneously as they serve different purposes.

### Test Individual Components:
```bash
# Test Shelly switch control
python ControlSwitch.py

# Test Telegram messaging
python TelegramButtonsGen.py
```

## 🌐 Web Interface Features

- **Real-time monitoring** of all devices via Server-Sent Events
- **Mobile responsive** design for phone/tablet access
- **Interactive gate control** with status feedback
- **Color-coded status**: Open (red), Closed (green), Offline (red)
- **Battery level display** for gate sensors
- **Network access** from any device on local network

### Web Interface Setup
1. Configure Windows Firewall to allow port 8000
2. Access from any device: `http://COMPUTER_IP:8000`
3. Interface automatically adapts to mobile devices

## 🏠 Home Assistant Setup

### Required Sensors:
Your Home Assistant must have the following entities configured:

**For gate sensors (example with Xiaomi Aqara):**
- `binary_sensor.big_gate_sensor_opening` - Big gate door sensor
- `sensor.big_gate_sensor_battery` - Big gate battery level
- `binary_sensor.small_gate_sensor_opening` - Small gate door sensor  
- `sensor.small_gate_sensor_battery` - Small gate battery level

### Entity Naming Convention:
The system automatically derives battery sensor names by:
- Replacing `_opening` with `_battery`
- Changing `binary_sensor.` to `sensor.`

### Long-lived Access Token:
1. Go to Home Assistant → Profile → Long-lived access tokens
2. Create new token
3. Copy token to configuration files

## 📱 Telegram Bot Setup
1. Message @BotFather on Telegram
2. Create new bot with `/newbot`
3. Get bot token and your chat ID
4. Add credentials to configuration files

## 🔧 Hardware Setup

### Gate Sensors:
- **Recommended**: Xiaomi Aqara door/window sensors
- Must be integrated with Home Assistant
- Battery reporting capability required

### Shelly Switch (Big Gate Only):
- **Model**: Shelly 1 Plus or compatible
- Connected to gate motor control
- Accessible via local network IP

### Network Requirements:
- All devices on same local network
- Home Assistant accessible from monitoring computer
- Shelly device accessible via HTTP

## 📊 Monitoring Features

### Gate Status Detection:
- **Real-time monitoring** of open/closed states
- **Battery level tracking** with two-tier alerts
- **Automatic retry logic** for failed operations

### User Interaction:
- **Telegram buttons** for manual control decisions
- **Web interface buttons** for immediate gate control
- **Configurable delays** for different scenarios

### Error Handling:
- **Robust network error recovery**
- **Comprehensive logging** for troubleshooting
- **Graceful degradation** when services unavailable

## 🔒 Security & Privacy

- **Local operation** - no cloud dependencies after Tuya migration
- **Network security** - all communication within local network
- **Token protection** - never commit real credentials to repository
- **Firewall configuration** - controlled access to web interface

### Security Best Practices:
- Use strong Home Assistant passwords
- Regular token rotation recommended
- Monitor network access logs
- Keep software dependencies updated

## 📁 Project Structure

```
GateCheck/
├── GateCheck.py              # Big gate monitoring with control
├── GateCheckSmall.py         # Small gate monitoring (read-only)
├── Online_check_web.py       # Web interface for all devices
├── ControlSwitch.py          # Shelly switch control module
├── TelegramButtonsGen.py     # Telegram bot interface module
├── gate_check.ini            # Configuration for gate programs
├── online_check.ini          # Configuration for web interface
├── templates/
│   └── status.html           # Web interface HTML template
├── .gitignore               # Git ignore rules
└── README.md                # This file
```

## 🐛 Troubleshooting

### Common Issues:

**Home Assistant Connection:**
- Verify HA IP address and port (default 8123)
- Check long-lived access token validity
- Ensure HA is accessible from monitoring computer

**Entity Not Found:**
- Verify entity names in Home Assistant
- Check battery sensor naming convention
- Ensure sensors are properly integrated

**Web Interface Access:**
- Configure Windows Firewall for port 8000
- Verify computer IP address with `ipconfig`
- Check if web service is listening with `netstat -an | findstr :8000`

**Telegram Issues:**
- Confirm bot token and chat ID
- Test bot independently with TelegramButtonsGen.py
- Check network connectivity to Telegram servers

**Shelly Control:**
- Verify Shelly IP address and network connectivity
- Test manual HTTP requests to Shelly API
- Check Shelly device status and configuration

## 🔄 Migration from Tuya

This system has been fully migrated from Tuya Cloud to Home Assistant for:
- **Improved reliability** - no dependency on cloud services
- **Faster response times** - local network communication
- **Enhanced privacy** - all data stays local
- **Reduced complexity** - no cloud API credentials needed

## 📄 License

This project is open source. Please ensure compliance with local regulations and device manufacturer guidelines.

## 🤝 Contributing

Contributions welcome! Please:
- Test thoroughly before submitting pull requests
- Ensure no private credentials in commits
- Document any configuration changes
- Follow existing code style and structure

---

**Note**: Replace all example IP addresses, tokens, and entity names with your actual values. Never commit real credentials to version control.