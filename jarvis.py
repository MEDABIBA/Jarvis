from jarvis_message import message
from handle import handle

while True:
    prompt = {
    'role': 'user',
    "content": input("> ")
}
    print("Jarvis: ", handle(prompt, message)["message"]["content"])