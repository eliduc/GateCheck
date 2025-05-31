import requests
import time

class Shelly1Plus:
    def __init__(self, ip_address):
        self.base_url = f"http://{ip_address}"

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
        response = requests.post(url, json=payload)
        return response.json()

def control_shelly_switch(ip_address):
    shelly = Shelly1Plus(ip_address)
    
    try:
        # Turn on the switch
        result = shelly.turn_on()
        
        # Wait for 0.2 seconds
        time.sleep(0.2)
        
        # Turn off the switch
        result = shelly.turn_off()
        
    except requests.exceptions.RequestException as e:
        print(f"An error occurred in switch: {e}")

if __name__ == "__main__":
    # This code will only run if the script is executed directly
    # It won't run when the module is imported
    ip_night = "192.168.2.37"
    ip_off = "192.168.2.38"
    
    control_shelly_switch(ip_night)
    time.sleep(2)
    control_shelly_switch(ip_off)