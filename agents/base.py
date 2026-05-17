import requests
import config

class BaseAgent:
    def __init__(self, role, system_prompt):
        self.role = role
        self.system_prompt = system_prompt
        self.memory = []

    def add_memory(self, user, text):
        self.memory.append(f"{user}: {text}")

        if len(self.memory) > 12:
            self.memory.pop(0)

    def build_messages(self, user_message):
        history = "\n".join(self.memory)

        return f"""
{self.system_prompt}

История разговора:
{history}

Новое сообщение:
{user_message}

Отвечай ТОЛЬКО как {self.role}.
Не говори как ChatGPT.
Будь живым участником команды.
"""

    async def generate_response(self, user_message):
        self.add_memory("User", user_message)

        headers = {
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": config.OPENROUTER_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": self.build_messages(user_message)
                }
            ]
        }

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60
        )

        data = response.json()

        answer = data["choices"][0]["message"]["content"]

        self.add_memory(self.role, answer)

        return answer