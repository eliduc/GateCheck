import requests

TOKEN = '8163246799:AAGovrIUQh6N9ckRA0kjiDEQ2x2IUUEZqyA'

url = f'https://api.telegram.org/bot{TOKEN}/getUpdates'

response = requests.get(url)
data = response.json()

print(data)
