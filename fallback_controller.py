from models import GreenhouseState, PlantUnit


class FallbackController:
    def __init__(self, greenhouse: GreenhouseState):
        self.greenhouse = greenhouse

    def step(self):
        if not self.greenhouse.fallback_mode:
            return

        for unit in self.greenhouse.plants.values():
            self._control_plant(unit)

    def _control_plant(self, unit: PlantUnit):
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
                self._add_event(f"{profile.name}: резервный режим включил вентилятор")
            devices.fan_on = True
        elif state.temperature < profile.temp_max - 1.5:
            devices.fan_on = False

        if state.temperature > profile.temp_max + 2:
            if devices.lamp_level > 0:
                self._add_event(f"{profile.name}: резервный режим выключил лампу из-за перегрева")
            self._set_lamp_level(devices, 0)
        else:
            if state.light_level < profile.light_min and state.light_today < profile.light_goal:
                level = self._recommended_lamp_level(profile, state)
                if level != devices.lamp_level:
                    self._add_event(f"{profile.name}: резервный режим поставил лампу на {level}%")
                self._set_lamp_level(devices, level)
            else:
                self._set_lamp_level(devices, 0)

        can_water = self.greenhouse.tick - state.last_watering_tick >= profile.min_watering_gap

        if state.soil_moisture < profile.soil_min and can_water:
            if self.greenhouse.water_tank_ok:
                devices.pump_on = True
                state.last_watering_tick = self.greenhouse.tick
                self._add_event(f"{profile.name}: резервный режим включил полив")
            else:
                self._add_event(f"{profile.name}: резервный режим не смог включить полив, нет воды")
        elif state.soil_moisture > profile.soil_max:
            devices.pump_on = False

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