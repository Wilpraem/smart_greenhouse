import os
import select
import sys

from models import create_default_greenhouse
from simulator import GreenhouseSimulator
from fallback_controller import FallbackController
from ai_controller import AIController
from api_server import GreenhouseAPIServer


NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")


def format_time(minute_of_day: int) -> str:
    hours = minute_of_day // 60
    minutes = minute_of_day % 60
    return f"{hours:02d}:{minutes:02d}"


def clear_screen():
    print("\033[2J\033[H", end="")


def short_name(key: str) -> str:
    return {
        "orchid": "Орхидея",
        "anthurium": "Антуриум",
        "fern": "Папоротник",
        "banana": "Банан",
    }.get(key, key)


def yes_no(value: bool) -> str:
    return "OK" if value else "ERR"


def mode_text(greenhouse) -> str:
    if greenhouse.fallback_mode:
        return "Резервный"
    if greenhouse.ai_enabled:
        return "ИИ"
    return "Локальный"


def print_commands():
    print("Команды:")
    print(" heat     - создать сильную жару")
    print(" dry      - сделать почву сухой")
    print(" dark     - уменьшить освещённость")
    print(" over     - создать перелив")
    print(" nowater  - отключить воду в баке")
    print(" waterok  - восстановить воду")
    print(" sensor   - включить ошибку датчика")
    print(" sensorok - восстановить датчик")
    print(" power    - отключить питание")
    print(" powerok  - восстановить питание")
    print(" netoff   - отключить интернет")
    print(" neton    - включить интернет")
    print(" clear    - сбросить все ручные аварии")
    print(" help     - показать команды")
    print(" quit     - выйти")


def print_screen(simulator: GreenhouseSimulator):
    g = simulator.greenhouse
    clear_screen()

    print("УМНАЯ ОРАНЖЕРЕЯ")
    print(
        f"Время {format_time(g.minute_of_day)} | "
        f"Тик {g.tick} | "
        f"Режим {mode_text(g)} | "
        f"Net {yes_no(g.internet_ok)} | "
        f"Power {yes_no(g.power_ok)} | "
        f"Water {yes_no(g.water_tank_ok)} | "
        f"Sensor {yes_no(g.sensor_ok)}"
    )
    print("-" * 110)

    for key, unit in g.plants.items():
        s = unit.state
        d = unit.devices

        print(
            f"{short_name(key):<11} "
            f"T:{s.temperature:>4.1f}C  "
            f"Почва:{s.soil_moisture:>5.1f}%  "
            f"Свет:{s.light_level:>5}  "
            f"Лампа:{d.lamp_level:>3}%  "
            f"Вент:{'ON' if d.fan_on else 'OFF':<3}  "
            f"Полив:{'ON' if d.pump_on else 'OFF':<3}  "
            f"Статус: {s.status}"
        )
        print(
            f"{'':<11} "
            f"Цветение: {s.flowering_prediction:<8}  "
            f"Плодоношение: {s.fruiting_prediction}"
        )

    print("-" * 110)
    print("Последние события:")
    events = simulator.get_last_events(5)
    if events:
        for event in events:
            print(" -", event)
    else:
        print(" - Событий пока нет")

    print("-" * 110)
    print_commands()


def do_auto_step(simulator: GreenhouseSimulator, fallback: FallbackController, ai: AIController):
    simulator.step()

    if simulator.greenhouse.fallback_mode:
        fallback.step()
    else:
        ai.step()

    if simulator.greenhouse.fallback_mode:
        fallback.step()


def handle_command(command: str, simulator: GreenhouseSimulator):
    command = command.strip().lower()

    if not command:
        return True

    if command == "heat":
        simulator.force_heatwave()
    elif command == "dry":
        simulator.force_dry_soil()
    elif command == "dark":
        simulator.force_low_light()
    elif command == "over":
        simulator.force_overwater()
    elif command == "nowater":
        simulator.set_water_tank_empty(True)
    elif command == "waterok":
        simulator.set_water_tank_empty(False)
    elif command == "sensor":
        simulator.set_sensor_fault(True)
    elif command == "sensorok":
        simulator.set_sensor_fault(False)
    elif command == "power":
        simulator.set_power_outage(True)
    elif command == "powerok":
        simulator.set_power_outage(False)
    elif command == "netoff":
        simulator.internet_down()
    elif command == "neton":
        simulator.internet_up()
    elif command == "clear":
        simulator.clear_emergencies()
    elif command == "help":
        pass
    elif command == "quit":
        return False

    return True


def main():
    greenhouse = create_default_greenhouse()
    simulator = GreenhouseSimulator(greenhouse)
    fallback = FallbackController(greenhouse)
    ai = AIController(greenhouse, NVIDIA_API_KEY)
    api_server = GreenhouseAPIServer(greenhouse, host="0.0.0.0", port=8000)
    api_server.start()

    running = True

    try:
        while running:
            print_screen(simulator)

            ready, _, _ = select.select([sys.stdin], [], [], 1.0)

            if ready:
                command = sys.stdin.readline().strip()
                running = handle_command(command, simulator)
            else:
                do_auto_step(simulator, fallback, ai)

    finally:
        api_server.stop()


if __name__ == "__main__":
    main()