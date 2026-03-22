import random
from models import GreenhouseState, PlantUnit


class GreenhouseSimulator:
    def __init__(self, greenhouse: GreenhouseState):
        self.greenhouse = greenhouse

    def step(self):
        self.greenhouse.tick += 1
        self.greenhouse.minute_of_day += self.greenhouse.step_minutes

        if self.greenhouse.minute_of_day >= 24 * 60:
            self.greenhouse.minute_of_day = 0
            self._reset_new_day()

        for unit in self.greenhouse.plants.values():
            self._update_environment(unit)

            if not self.greenhouse.fallback_mode and not self.greenhouse.ai_enabled:
                self._auto_control(unit)

            self._update_status(unit)
            self._update_predictions(unit)

    def _reset_new_day(self):
        self._add_event("Начался новый день.")
        for unit in self.greenhouse.plants.values():
            unit.state.light_today = 0

    def _update_environment(self, unit: PlantUnit):
        state = unit.state
        devices = unit.devices

        if not self.greenhouse.power_ok:
            self._set_lamp_level(devices, 0)
            devices.fan_on = False
            devices.pump_on = False

        base_light = self._day_light_level(self.greenhouse.minute_of_day)

        state.temperature += random.uniform(-0.3, 0.3)
        state.air_humidity += random.uniform(-0.8, 0.8)
        state.soil_moisture -= random.uniform(0.5, 1.2)
        state.light_level = base_light + random.randint(-250, 250)

        if self.greenhouse.power_ok and devices.fan_on:
            state.temperature -= random.uniform(0.6, 1.1)
            state.air_humidity -= random.uniform(0.2, 0.5)

        if self.greenhouse.power_ok and devices.lamp_level > 0:
            extra_light = int(2500 * (devices.lamp_level / 100))
            state.light_level += extra_light
            state.temperature += 0.15 + 0.35 * (devices.lamp_level / 100)
            state.light_today += self.greenhouse.step_minutes

        if self.greenhouse.power_ok and devices.pump_on:
            if self.greenhouse.water_tank_ok:
                state.soil_moisture += random.uniform(8, 14)
            else:
                self._add_event(f"{unit.profile.name}: полив не выполнен, в баке нет воды")

        state.temperature = self._clamp(state.temperature, 10, 45)
        state.air_humidity = self._clamp(state.air_humidity, 20, 95)
        state.soil_moisture = self._clamp(state.soil_moisture, 0, 100)
        state.light_level = int(self._clamp(state.light_level, 0, 20000))

        devices.pump_on = False

    def _auto_control(self, unit: PlantUnit):
        profile = unit.profile
        state = unit.state
        devices = unit.devices

        if not self.greenhouse.power_ok or not self.greenhouse.sensor_ok:
            devices.pump_on = False
            devices.fan_on = False
            self._set_lamp_level(devices, 0)
            return

        if state.temperature > profile.temp_max:
            if not devices.fan_on:
                self._add_event(f"{profile.name}: включён вентилятор из-за перегрева")
            devices.fan_on = True
        elif state.temperature < profile.temp_max - 1.5:
            devices.fan_on = False

        if (
            state.light_level < profile.light_min
            and state.light_today < profile.light_goal
            and state.temperature <= profile.temp_max
        ):
            new_level = self._recommended_lamp_level(profile, state)
            if new_level != devices.lamp_level:
                self._add_event(f"{profile.name}: лампа установлена на {new_level}%")
            self._set_lamp_level(devices, new_level)
        else:
            self._set_lamp_level(devices, 0)

        can_water = self.greenhouse.tick - state.last_watering_tick >= profile.min_watering_gap

        if state.soil_moisture < profile.soil_min and can_water:
            if self.greenhouse.water_tank_ok:
                devices.pump_on = True
                state.last_watering_tick = self.greenhouse.tick
                self._add_event(f"{profile.name}: включён полив, почва сухая")
            else:
                self._add_event(f"{profile.name}: нужен полив, но воды нет")

        if state.soil_moisture > profile.soil_max:
            devices.pump_on = False

        if state.temperature > profile.temp_max + 2:
            self._set_lamp_level(devices, 0)
            self._add_event(f"{profile.name}: лампа отключена из-за сильного перегрева")

    def _update_status(self, unit: PlantUnit):
        profile = unit.profile
        state = unit.state

        if not self.greenhouse.power_ok:
            state.status = "Нет питания"
            state.growth_score -= 1.2
            state.stress += 1
        elif not self.greenhouse.sensor_ok:
            state.status = "Ошибка датчика"
            state.growth_score -= 0.8
            state.stress += 1
        elif not self.greenhouse.water_tank_ok and state.soil_moisture < profile.soil_min:
            state.status = "Нет воды"
            state.growth_score -= 1.0
            state.stress += 1
        elif state.temperature > profile.temp_max + 2:
            state.status = "Критический перегрев"
            state.stress += 2
        elif state.temperature > profile.temp_max:
            state.status = "Перегрев"
            state.stress += 1
        elif state.soil_moisture < profile.soil_min:
            state.status = "Сухая почва"
            state.stress += 1
        elif state.soil_moisture > profile.soil_max:
            state.status = "Риск перелива"
            state.stress += 1
        elif state.light_level < profile.light_min and state.light_today < profile.light_goal:
            state.status = "Мало света"
        else:
            state.status = "Норма"

        good_temp = profile.temp_min <= state.temperature <= profile.temp_max
        good_soil = profile.soil_min <= state.soil_moisture <= profile.soil_max
        good_light = state.light_level >= profile.light_min or state.light_today >= profile.light_goal

        if self.greenhouse.power_ok and self.greenhouse.sensor_ok and good_temp and good_soil and good_light:
            state.growth_score += 1.2
        else:
            state.growth_score -= 0.8

        state.growth_score = self._clamp(state.growth_score, 0, 100)

    def _update_predictions(self, unit: PlantUnit):
        state = unit.state
        score = state.growth_score - state.stress * 0.4

        if score >= 75:
            state.flowering_prediction = "Высокая"
        elif score >= 45:
            state.flowering_prediction = "Средняя"
        else:
            state.flowering_prediction = "Низкая"

        if unit.profile.can_fruit:
            if score >= 80:
                state.fruiting_prediction = "Высокая"
            elif score >= 50:
                state.fruiting_prediction = "Средняя"
            else:
                state.fruiting_prediction = "Низкая"
        else:
            state.fruiting_prediction = "—"

    def force_heatwave(self):
        for unit in self.greenhouse.plants.values():
            unit.state.temperature += 5
        self._add_event("Создана авария: сильная жара")

    def force_dry_soil(self):
        for unit in self.greenhouse.plants.values():
            unit.state.soil_moisture = self._clamp(unit.state.soil_moisture - 20, 0, 100)
        self._add_event("Создана авария: сухая почва")

    def force_low_light(self):
        for unit in self.greenhouse.plants.values():
            unit.state.light_level = max(0, unit.state.light_level - 4000)
        self._add_event("Создана авария: мало света")

    def force_overwater(self):
        for unit in self.greenhouse.plants.values():
            unit.state.soil_moisture = self._clamp(unit.state.soil_moisture + 25, 0, 100)
        self._add_event("Создана авария: перелив")

    def set_water_tank_empty(self, empty: bool):
        self.greenhouse.water_tank_ok = not empty
        if empty:
            self._add_event("Авария: в баке нет воды")
        else:
            self._add_event("Вода восстановлена")

    def set_sensor_fault(self, fault: bool):
        self.greenhouse.sensor_ok = not fault
        if fault:
            self._add_event("Авария: датчик неисправен")
        else:
            self._add_event("Датчик восстановлен")

    def set_power_outage(self, outage: bool):
        self.greenhouse.power_ok = not outage
        if outage:
            self._add_event("Авария: питание отключено")
            for unit in self.greenhouse.plants.values():
                unit.devices.pump_on = False
                unit.devices.fan_on = False
                self._set_lamp_level(unit.devices, 0)
        else:
            self._add_event("Питание восстановлено")

    def internet_down(self):
        self.greenhouse.internet_ok = False
        self.greenhouse.fallback_mode = True
        self._add_event("Интернет пропал. Система перешла в резервный режим.")

    def internet_up(self):
        self.greenhouse.internet_ok = True
        self.greenhouse.fallback_mode = False
        self._add_event("Интернет восстановлен. Основной режим снова доступен.")

    def clear_emergencies(self):
        self.greenhouse.water_tank_ok = True
        self.greenhouse.sensor_ok = True
        self.greenhouse.power_ok = True
        self._add_event("Все ручные аварии сброшены")

    def get_last_events(self, count: int = 6):
        return self.greenhouse.events[-count:]

    def _recommended_lamp_level(self, profile: PlantProfile, state: PlantState):
        deficit = profile.light_min - state.light_level

        if deficit >= 4000:
            return 100
        if deficit >= 2500:
            return 70
        if deficit >= 1200:
            return 45
        return 25

    def _set_lamp_level(self, devices, level: int):
        level = int(self._clamp(level, 0, 100))
        devices.lamp_level = level
        devices.lamp_on = level > 0

    def _day_light_level(self, minute_of_day: int):
        hour = minute_of_day // 60

        if 6 <= hour < 9:
            return 2500
        if 9 <= hour < 12:
            return 5000
        if 12 <= hour < 16:
            return 8000
        if 16 <= hour < 19:
            return 4000
        return 500

    def _add_event(self, text: str):
        if not self.greenhouse.events or self.greenhouse.events[-1] != text:
            self.greenhouse.events.append(text)

    def _clamp(self, value, minimum, maximum):
        return max(minimum, min(value, maximum))