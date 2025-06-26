import requests
import time

class Shelly1Plus:
    def __init__(self, ip_address):
        self.base_url = f"http://{ip_address}"
        self.ip_address = ip_address

    def test_connection(self):
        """Test if Shelly device is reachable"""
        try:
            url = f"{self.base_url}/shelly"
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except:
            return False

    def turn_on(self):
        return self._send_command("on")

    def turn_off(self):
        return self._send_command("off")

    def _send_command(self, command):
        url = f"{self.base_url}/rpc/Switch.Set"
        payload = {
            "id": 0,
            "on": command == "on"
        }
        # Добавляем timeout для более быстрого обнаружения проблем
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()  # Вызывает исключение при HTTP ошибках
        return response.json()

def control_shelly_switch(ip_address):
    shelly = Shelly1Plus(ip_address)
    
    try:
        # Проверяем подключение к Shelly перед началом операции
        if not shelly.test_connection():
            print(f"Cannot connect to Shelly device at {ip_address}")
            return False
        
        # Небольшая пауза перед началом для стабилизации
        time.sleep(0.1)
        
        # Turn on the switch
        result_on = shelly.turn_on()
        print(f"Switch ON result: {result_on}")
        
        # Оптимальное время для приводов Nice: 200ms (0.2 сек)
        # Это время проверено на практике и работает с большинством приводов Nice
        time.sleep(0.2)
        
        # Turn off the switch
        result_off = shelly.turn_off()
        print(f"Switch OFF result: {result_off}")
        
        # Небольшая пауза после выключения для завершения операции
        time.sleep(0.1)
        
        # Проверяем успешность операции
        if result_on.get('was_on') is False and result_off.get('was_on') is True:
            print("Gate operation completed successfully")
            return True
        else:
            print(f"Gate operation may have failed: ON={result_on}, OFF={result_off}")
            return False
        
    except requests.exceptions.Timeout:
        print("Timeout error: Shelly device not responding")
        raise
    except requests.exceptions.ConnectionError:
        print("Connection error: Cannot reach Shelly device")
        raise  
    except requests.exceptions.RequestException as e:
        print(f"Network error occurred in switch: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error in switch operation: {e}")
        raise

if __name__ == "__main__":
    # This code will only run if the script is executed directly
    # It won't run when the module is imported
    ip_night = "192.168.2.37"
    ip_off = "192.168.2.38"
    
    control_shelly_switch(ip_night)
    time.sleep(2)
    control_shelly_switch(ip_off)