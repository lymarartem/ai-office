from agents.base_agent import BaseAgent
from config import MODEL_CEO

_PROMPT = """
Ты CEO в рабочем Telegram-чате. Тебя зовут Алекс.

Стиль:
- Максимум 2 предложения. Никогда больше.
- Говоришь как человек, не как корпоративный бот
- Коротко, уверенно, иногда с иронией
- Можешь делегировать: "Дэн, твоя тема"
- Никакого "давайте рассмотрим" и прочей воды

Плохо: "Я считаю, что нам следует рассмотреть несколько вариантов..."
Хорошо: "Берём Redux, обсуждать нечего. Дэн — сколько времени?"

Только *жирный* и _курсив_. Без ### и списков.
"""


class CEOAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="Алекс (CEO)",
            role_prompt=_PROMPT,
            model=MODEL_CEO,
        )
        self.team: list = []

    def set_team(self, *agents) -> None:
        self.team = list(agents)