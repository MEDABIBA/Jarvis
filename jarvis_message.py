from schemas import Message

message: list[Message] = [{
    'role': 'system',
    "content": "Begin EVERY response by addressing the user as 'Shef'" # Instructions
}]