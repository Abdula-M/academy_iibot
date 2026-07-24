import asyncio
from openai import AsyncOpenAI, APIStatusError

async def main():
    client = AsyncOpenAI(
        api_key="sk-3d994f22fbe4470b83afc5a321dea090",
        base_url="https://api.deepseek.com"
    )
    try:
        response = await client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[{"role": "system", "content": "test"}, {"role": "user", "content": "hello"}],
            max_tokens=2048,
            temperature=0.7,
        )
        print(response)
    except APIStatusError as e:
        print("APIStatusError:", e.status_code)
        print("Response body:", e.response.text)
    except Exception as e:
        print("Exception:", e)

asyncio.run(main())
