import json
import time
from collections import deque

import requests
from models import GreenhouseState


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

        self.last_recovery_check = 0.0
        self.recovery_check_interval = 20.0

        if self.api_key:
            self.greenhouse.ai_enabled = True
            self._add_event("ИИ-контроллер включён.")
        else:
            self.greenhouse.ai_enabled = False
            self._add_event("API ключ не задан. Работает обычная логика без ИИ.")

    def step(self):
        if not self.greenhouse.ai_enabled:
            return

        if self.greenhouse.fallback_mode:
            self._try_restore_from_fallback()
            return

        if not self.greenhouse.internet_ok:
            return

        if not self._can_send_request():
            self._add_event("Достигнут лимит 40 запросов в минуту. ИИ временно пропущен.")
            return

        try:
            decisions = self._ask_ai_for_all_plants()
            self._apply_all_decisions(decisions)
            self.fail_count = 0
        except Exception:
            self.fail_count += 1
            self._add_event("ИИ временно не ответил, решение пропущено")

        if self.fail_count >= 2:
            self.greenhouse.internet_ok = False
            self.greenhouse.fallback_mode = True
            self._add_event("ИИ недоступен несколько запросов подряд. Система перешла в резервный режим.")

    def _try_restore_from_fallback(self):
        now = time.monotonic()

        if now - self.last_recovery_check < self.recovery_check_interval:
            return

        self.last_recovery_check = now

        try:
            ok = self._ping_ai()

            if ok:
                self.greenhouse.internet_ok = True
                self.greenhouse.fallback_mode = False
                self.fail_count = 0
                self._add_event("Связь с ИИ восстановлена. Система вернулась в основной режим.")
        except Exception:
            pass

    def _ping_ai(self) -> bool:
        if not self._can_send_request():
            return False

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Отвечай только JSON."},
                {"role": "user", "content": '{"ok":true}'},
            ],
            "max_tokens": 20,
            "temperature": 0.0,
            "top_p": 0.1,
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
        return True

    def _can_send_request(self) -> bool:
        now = time.monotonic()

        while self.request_times and now - self.request_times[0] >= 60:
            self.request_times.popleft()

        return len(self.request_times) < self.max_requests_per_minute

    def _register_request(self):
        self.request_times.append(time.monotonic())

    def _ask_ai_for_all_plants(self):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        plants_data = []
        for key, unit in self.greenhouse.plants.items():
            profile = unit.profile
            state = unit.state

            plants_data.append({
                "key": key,
                "name": profile.name,
                "temperature": round(state.temperature, 1),
                "air_humidity": round(state.air_humidity, 1),
                "soil_moisture": round(state.soil_moisture, 1),
                "temp_min": profile.temp_min,
                "temp_max": profile.temp_max,
                "soil_min": profile.soil_min,
                "soil_max": profile.soil_max,
                "light_level": state.light_level,
                "light_min": profile.light_min,
                "light_today": state.light_today,
                "light_goal": profile.light_goal,
                "status": state.status,
            })

        system_text = (
            "Ты управляешь умной оранжереей. "
            "Тебе переданы сразу все растения. "
            "Для каждого растения верни решение в JSON без markdown и без пояснений вне JSON. "
            "Формат ответа строго такой: "
            '{"decisions":[{"key":"orchid","watering":false,"lighting":true,"fan":false,"reason":"кратко"}]}'
        )

        user_text = (
            "Вот данные по всем растениям:\n"
            f"{json.dumps(plants_data, ensure_ascii=False)}\n"
            "Нужно отдельно принять решение для каждого растения."
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ],
            "max_tokens": 500,
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
        parsed = self._parse_json(content)

        decisions = parsed.get("decisions", [])
        if not isinstance(decisions, list):
            raise ValueError("ИИ вернул неверный формат decisions")

        return decisions

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

    def _apply_all_decisions(self, decisions: list):
        decision_map = {}

        for item in decisions:
            key = item.get("key")
            if key:
                decision_map[key] = item

        for key, unit in self.greenhouse.plants.items():
            decision = decision_map.get(key)
            if decision:
                self._apply_decision(unit, decision)

    def _apply_decision(self, unit, decision: dict):
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
        self.greenhouse.events.append(text)
