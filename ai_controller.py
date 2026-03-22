import json
import requests

from models import GreenhouseState, PlantUnit


class AIController:
    def __init__(self, greenhouse: GreenhouseState, api_key: str):
        self.greenhouse = greenhouse
        self.api_key = api_key.strip()
        self.url = "https://integrate.api.nvidia.com/v1/chat/completions"
        self.model = "qwen/qwen3.5-122b-a10b"
        self.fail_count = 0

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

        if not self.greenhouse.power_ok or not self.greenhouse.sensor_ok:
            return

        all_failed = True

        for unit in self.greenhouse.plants.values():
            try:
                decision = self._ask_ai(unit)
                self._apply_decision(unit, decision)
                all_failed = False
            except Exception:
                self._add_event(f"{unit.profile.name}: ИИ временно не ответил")

        if all_failed:
            self.fail_count += 1
        else:
            self.fail_count = 0

        if self.fail_count >= 2:
            self.greenhouse.internet_ok = False
            self.greenhouse.fallback_mode = True
            self._add_event("ИИ недоступен несколько запросов подряд. Система перешла в резервный режим.")

    def _ask_ai(self, unit: PlantUnit):
        profile = unit.profile
        state = unit.state

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        system_text = (
            "Ты управляешь умной оранжереей. "
            "Отвечай только JSON без markdown. "
            'Формат: {"watering": true, "lighting": false, "fan": false, "reason": "кратко"}'
        )

        user_text = (
            f"Растение: {profile.name}\n"
            f"Температура: {state.temperature:.1f}\n"
            f"Мин температура: {profile.temp_min}\n"
            f"Макс температура: {profile.temp_max}\n"
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

        response = requests.post(self.url, headers=headers, json=payload, timeout=25)
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

        return json.loads(cleaned[start:end + 1])

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

        new_lamp_level = self._recommended_lamp_level(profile, state) if want_lamp else 0
        if new_lamp_level != devices.lamp_level:
            self._set_lamp_level(devices, new_lamp_level)
            changes.append(f"лампа {new_lamp_level}%")

        if want_pump:
            if self.greenhouse.water_tank_ok:
                devices.pump_on = True
                state.last_watering_tick = self.greenhouse.tick
                changes.append("полив включён")
            else:
                self._add_event(f"{profile.name}: ИИ запросил полив, но воды нет")
                devices.pump_on = False
        else:
            devices.pump_on = False

        if changes:
            text = f"{profile.name}: ИИ решил — " + ", ".join(changes)
            if reason:
                text += f". Причина: {reason}"
            self._add_event(text)

    def _recommended_lamp_level(self, profile, state):
        deficit = profile.light_min - state.light_level

        if deficit >= 4000:
            return 100
        if deficit >= 2500:
            return 70
        if deficit >= 1200:
            return 45
        return 25

    def _set_lamp_level(self, devices, level: int):
        devices.lamp_level = max(0, min(100, int(level)))
        devices.lamp_on = devices.lamp_level > 0

    def _add_event(self, text: str):
        if not self.greenhouse.events or self.greenhouse.events[-1] != text:
            self.greenhouse.events.append(text)