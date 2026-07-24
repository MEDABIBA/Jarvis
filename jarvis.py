import ollama

while True:
    prompt = input("> ")

    response = ollama.chat(model='qwen:7b', messages=[
      {
        'role': 'user',
        'content': prompt,
      },
    ])
    print(response['message']['content'])