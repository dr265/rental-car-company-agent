import sys
sys.path.insert(0, r'C:\rental_car_company agent\backend')
import asyncio
from app.llm import chat_json

async def test():
    try:
        result = await chat_json([
            {'role': 'system', 'content': 'Reply with ONE JSON object only: {"reply": "...", "intent": "..."}'},
            {'role': 'user', 'content': 'hi'}
        ])
        print('Result:', result)
    except Exception as e:
        print('Error:', e)

asyncio.run(test())