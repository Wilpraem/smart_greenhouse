from dataclasses import dataclass, field


@dataclass
class PlantProfile:
    name: str
    temp_min: float
    temp_max: float
    soil_min: float
    soil_max: float
    light_min: int
    light_goal: int
    min_watering_gap: int
    can_fruit: bool = False


@dataclass
class PlantState:
    temperature: float
    air_humidity: float
    soil_moisture: float
    light_level: int
    light_today: int = 0
    last_watering_tick: int = -999
    growth_score: float = 50.0
    stress: int = 0
    status: str = "Норма"
    flowering_prediction: str = "Средняя"
    fruiting_prediction: str = "—"


@dataclass
class PlantDevices:
    pump_on: bool = False
    lamp_on: bool = False
    lamp_level: int = 0
    fan_on: bool = False


@dataclass
class PlantUnit:
    profile: PlantProfile
    state: PlantState
    devices: PlantDevices = field(default_factory=PlantDevices)


@dataclass
class GreenhouseState:
    tick: int = 0
    minute_of_day: int = 8 * 60
    step_minutes: int = 10
    internet_ok: bool = True
    ai_enabled: bool = True
    fallback_mode: bool = False

    water_tank_ok: bool = True
    sensor_ok: bool = True
    power_ok: bool = True

    events: list[str] = field(default_factory=list)
    plants: dict[str, PlantUnit] = field(default_factory=dict)


def create_default_greenhouse() -> GreenhouseState:
    greenhouse = GreenhouseState()

    greenhouse.plants["orchid"] = PlantUnit(
        profile=PlantProfile(
            name="Орхидея фаленопсис",
            temp_min=20,
            temp_max=28,
            soil_min=35,
            soil_max=65,
            light_min=5000,
            light_goal=720,
            min_watering_gap=10,
            can_fruit=False,
        ),
        state=PlantState(
            temperature=24,
            air_humidity=60,
            soil_moisture=48,
            light_level=5200,
        ),
    )

    greenhouse.plants["anthurium"] = PlantUnit(
        profile=PlantProfile(
            name="Антуриум",
            temp_min=21,
            temp_max=30,
            soil_min=40,
            soil_max=70,
            light_min=6000,
            light_goal=780,
            min_watering_gap=8,
            can_fruit=False,
        ),
        state=PlantState(
            temperature=25,
            air_humidity=65,
            soil_moisture=50,
            light_level=6100,
        ),
    )

    greenhouse.plants["fern"] = PlantUnit(
        profile=PlantProfile(
            name="Бостонский папоротник",
            temp_min=18,
            temp_max=26,
            soil_min=50,
            soil_max=80,
            light_min=3500,
            light_goal=600,
            min_watering_gap=6,
            can_fruit=False,
        ),
        state=PlantState(
            temperature=23,
            air_humidity=72,
            soil_moisture=60,
            light_level=3900,
        ),
    )

    greenhouse.plants["banana"] = PlantUnit(
        profile=PlantProfile(
            name="Банан",
            temp_min=22,
            temp_max=32,
            soil_min=45,
            soil_max=75,
            light_min=8000,
            light_goal=900,
            min_watering_gap=7,
            can_fruit=True,
        ),
        state=PlantState(
            temperature=27,
            air_humidity=64,
            soil_moisture=55,
            light_level=7600,
        ),
    )

    return greenhouse