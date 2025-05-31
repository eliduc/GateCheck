# GateCheck - Automated Gate Monitoring System

## 🚪 Description
Automated IoT system for monitoring and controlling gates using Tuya sensors, Shelly switches, and Telegram notifications with real-time battery monitoring.

## ✨ Features
- **Real-time gate monitoring** using Tuya IoT sensors
- **Automatic gate control** via Shelly 1 Plus switches
- **Telegram notifications** with interactive buttons
- **Battery level monitoring** with configurable alerts
- **Configurable timeouts** and retry logic
- **Async operation** for responsive monitoring

## 🛠️ Requirements
- Python 3.7+
- Tuya IoT Platform account and registered devices
- Telegram Bot (created via @BotFather)
- Shelly 1 Plus device for gate control
- Compatible gate position sensor (Tuya ecosystem)

## 📦 Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/eliduc/GateCheck.git
   cd GateCheck
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Setup configuration:**
   ```bash
   copy gate_check.ini.template gate_check.ini
   ```

4. **Edit configuration file:**
   Edit `gate_check.ini` and fill in your actual:
   - Tuya Cloud API credentials
   - Device IDs and IP addresses
   - Telegram bot token and chat ID
   - Timeout and battery threshold settings

## 🚀 Usage

**Run the monitoring system:**
```bash
python GateCheck.py
```

**Test individual components:**
```bash
# Test gate state checking
python Check_Gate_State.py

# Test Shelly switch control
python ControlSwitch.py

# Test Telegram messaging
python TelegramButtonsGen.py
```

## ⚙️ Configuration

### Tuya IoT Setup
1. Create account at https://iot.tuya.com/
2. Create Cloud Project and get API credentials
3. Link your gate sensor device

### Telegram Bot Setup
1. Message @BotFather on Telegram
2. Create new bot with `/newbot`
3. Get bot token and your chat ID

### Device Configuration
- **Gate Sensor**: Must be Tuya-compatible door/window sensor
- **Shelly Switch**: Shelly 1 Plus or compatible model
- **Network**: All devices on same local network

## 📊 Monitoring Features

- **Gate Status**: Open/Closed detection
- **Battery Alerts**: Two-level warning system
- **User Interaction**: Telegram buttons for manual control
- **Auto-Close**: Configurable automatic gate closing
- **Error Handling**: Robust error recovery and logging

## 🔒 Security Notes

- **Never commit** `gate_check.ini` with real credentials
- Use **environment variables** for production deployment
- Ensure **network security** for IoT devices
- Regular **token rotation** recommended

## 📁 Project Structure

```
GateCheck/
├── GateCheck.py              # Main monitoring application
├── Check_Gate_State.py       # Tuya sensor interface
├── ControlSwitch.py          # Shelly switch control
├── TelegramButtonsGen.py     # Telegram bot interface
├── requirements.txt          # Python dependencies
├── gate_check.ini.template   # Configuration template
├── .gitignore               # Git ignore rules
└── README.md                # This file
```

## 🐛 Troubleshooting

**Common issues:**
- **Device offline**: Check network connectivity
- **API errors**: Verify Tuya credentials and device registration
- **Telegram not working**: Confirm bot token and chat ID
- **Shelly not responding**: Check IP address and network

## 📄 License

This project is open source. Please ensure compliance with device manufacturer APIs and local regulations.

## 🤝 Contributing

Contributions welcome! Please feel free to submit issues and enhancement requests.
