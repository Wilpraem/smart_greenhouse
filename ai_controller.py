import json
import time
from collections import deque

import requests
from models import GreenhouseState, PlantUnit


class AIController:
    def __init__(self, greenhouse: GreenhouseState, api_key: str):
        self.greenhouse = greenhouse
        self.api_key = api_key.strip()
        self.url = "https://integrate.api.nvidia.com/v1/chat/completions"
        self.model = "qwen/qwen3.5-122b-a10b"
        self.fail_count = 0

        self.request_timeout_seconds = 30
        self.max_requests_per_minute = 40
        self.request_times = deque()

        if self.api_key:
            self.greenhouse.ai_enabled = True
            self._add_event("ИИ-контроллер включён.")
        else:
            self.greenhouse.ai_enabled = False
            self._add_event("API ключ не задан. Работает обычная логика без ИИ.")

    def step(self):
        if not self.greenhouse.ai_enabled:
            return

        if not self.greenhouse.internet_ok:
            return

        if self.greenhouse.fallback_mode:
            return

        all_failed = True

        for unit in self.greenhouse.plants.values():
            if not self._can_send_request():
                self._add_event("Достигнут лимит 40 запросов в минуту. ИИ временно пропущен.")
                break

            try:
                decision = self._ask_ai(unit)
                self._apply_decision(unit, decision)
                all_failed = False
            except Exception:
                self._add_event(f"{unit.profile.name}: ИИ временно не ответил, решение пропущено")

        if all_failed:
            self.fail_count += 1
        else:
            self.fail_count = 0

        if self.fail_count >= 2:
            self.greenhouse.internet_ok = False
            self.greenhouse.fallback_mode = True
            self._add_event("ИИ недоступен несколько запросов подряд. Система перешла в резервный режим.")

    def _can_send_request(self) -> bool:
        now = time.monotonic()

        while self.request_times and now - self.request_times[0] >= 60:
            self.request_times.popleft()

        return len(self.request_times) < self.max_requests_per_minute

    def _register_request(self):
        self.request_times.append(time.monotonic())

    def _ask_ai(self, unit: PlantUnit):
        profile = unit.profile
        state = unit.state

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        system_text = (
            "Ты управляешь умной оранжереей. "
            "Отвечай только JSON без markdown и без пояснений. "
            "Формат ответа: "
            "{\"watering\": true, \"lighting\": false, \"fan\": false, \"reason\": \"кратко\"}"
        )

        user_text = (
            f"Растение: {profile.name}\n"
            f"Температура: {state.temperature:.1f}\n"
            f"Мин температура: {profile.temp_min}\n"
            f"Макс температура: {profile.temp_max}\n"
            f"Влажность воздуха: {state.air_humidity:.1f}\n"
            f"Влажность почвы: {state.soil_moisture:.1f}\n"
            f"Мин влажность почвы: {profile.soil_min}\n"
            f"Макс влажность почвы: {profile.soil_max}\n"
            f"Освещённость: {state.light_level}\n"
            f"Минимальный свет: {profile.light_min}\n"
            f"Свет за день: {state.light_today}\n"
            f"Цель света за день: {profile.light_goal}\n"
            f"Статус: {state.status}\n"
            "Реши, включать ли полив, лампу и вентилятор."
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ],
            "max_tokens": 120,
            "temperature": 0.2,
            "top_p": 0.7,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }

        self._register_request()

        response = requests.post(
            self.url,
            headers=headers,
            json=payload,
            timeout=self.request_timeout_seconds,
        )
        response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"]

        return self._parse_json(content)

    def _parse_json(self, text: str):
        cleaned = text.strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "").replace("```", "").strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start == -1 or end == -1:
            raise ValueError("ИИ не вернул JSON")

        json_text = cleaned[start:end + 1]
        return json.loads(json_text)

    def _apply_decision(self, unit: PlantUnit, decision: dict):
        profile = unit.profile
        state = unit.state
        devices = unit.devices

        want_pump = bool(decision.get("watering", False))
        want_lamp = bool(decision.get("lighting", False))
        want_fan = bool(decision.get("fan", False))
        reason = str(decision.get("reason", "")).strip()

        can_water = self.greenhouse.tick - state.last_watering_tick >= profile.min_watering_gap

        if state.soil_moisture > profile.soil_max:
            want_pump = False

        if not can_water:
            want_pump = False

        if state.temperature > profile.temp_max:
            want_lamp = False

        changes = []

        if want_fan != devices.fan_on:
            devices.fan_on = want_fan
            changes.append(f"вентилятор {'включён' if want_fan else 'выключен'}")

        if want_lamp != devices.lamp_on:
            devices.lamp_on = want_lamp
            changes.append(f"лампа {'включена' if want_lamp else 'выключена'}")

        if want_pump:
            devices.pump_on = True
            state.last_watering_tick = self.greenhouse.tick
            changes.append("полив включён")
        else:
            devices.pump_on = False

        if changes:
            text = f"{profile.name}: ИИ решил — " + ", ".join(changes)
            if reason:
                text += f". Причина: {reason}"
            self._add_event(text)

    def _add_event(self, text: str):
        self.greenhouse.events.append(text)
