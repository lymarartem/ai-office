import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

print("KEY:", os.getenv("GROQ_API_KEY"))

client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[
        {
            "role": "user",
            "content": "Hello"
        }
    ]
)

print(response.choices[0].message.content)
