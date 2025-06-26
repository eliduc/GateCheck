
import tinytuya

def check_sensor(DEVICE_ID, ACCESS_ID, ACCESS_KEY, API_REGION):

    client = tinytuya.Cloud(
        apiRegion=API_REGION, 
        apiKey=ACCESS_ID, 
        apiSecret=ACCESS_KEY
    )

    # Get the sensor data from the soil sensor
    device_data = client.getstatus(DEVICE_ID)
    print(device_data)

    # Return the sensor state
    if 'result' in device_data:
        return True
    else:
        return False

if __name__ == '__main__':
    ACCESS_ID =  '55vg4wfxr7kaawk5g3k3'        
    ACCESS_KEY =  '3eb77057570b488ba7a245c72c9d1943'    
    API_REGION = 'eu'
    DEVICE_ID = 'bf51533407475bca2cuutt'
    print('Sensor_1:',check_sensor(DEVICE_ID, ACCESS_ID, ACCESS_KEY, API_REGION))
    DEVICE_ID = 'bfb18b1a64a9267088q5ss'
    print('Sensor_1:',check_sensor(DEVICE_ID, ACCESS_ID, ACCESS_KEY, API_REGION))
