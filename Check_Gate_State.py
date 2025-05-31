def check_gate(DEVICE_ID):
    
    import tinytuya
    import configparser
    
    
    config = configparser.ConfigParser()
    config_file = 'gate_check.ini'
    config.read(config_file)
    
    try:
        ACCESS_ID = config.get('tuya', 'ACCESS_ID')
        ACCESS_KEY = config.get('tuya', 'ACCESS_KEY')
        API_REGION = config.get('tuya', 'API_REGION')
    
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        print(f"Configuration Error: {e}")
        return False


    client = tinytuya.Cloud(
        apiRegion=API_REGION, 
        apiKey=ACCESS_ID, 
        apiSecret=ACCESS_KEY
    )

    # Authenticate and get the list of devices
    #devices = client.getdevices()  # Correct method to get the list of devices
    
    

    # Get the sensor data from the soil sensor
    device_data = client.getstatus(DEVICE_ID)
    
    if  'result' in device_data:
        #print(device_data)
        #moisture = device_data['result'][0]['value']
        #temp = device_data['result'][1]['value']
        #battery = device_data['result'][4]['value']
        
        gate_closed = not device_data['result'][0]['value']
        battery = device_data['result'][1]['value']
        return (gate_closed, battery)        
    else:
        return False
        


if __name__ == "__main__":

    DEVICE_ID = 'bfb18b1a64a9267088q5ss'


    result = check_gate(DEVICE_ID)
 
    # Display the sensor data
    if result:
        print(f"Closed: {result[0]}")
        print(f"Battery: {result[1]}")
        #print(f"Battery: {battery}")
        #print(result)
    else:
        print(f"Failed to retrieve sensor data")

