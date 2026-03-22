import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class GreenhouseAPIServer:
    def __init__(self, greenhouse, host="0.0.0.0", port=8000):
        self.greenhouse = greenhouse
        self.host = host
        self.port = port
        self.httpd = None
        self.thread = None

    def start(self):
        greenhouse = self.greenhouse

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/snapshot":
                    data = build_snapshot(greenhouse)
                    body = json.dumps(data, ensure_ascii=False).encode("utf-8")

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path == "/health":
                    body = b'{"ok": true}'

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_response(404)
                self.end_headers()

            def log_message(self, format, *args):
                return

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


def build_snapshot(greenhouse):
    plants = []

    for key, unit in greenhouse.plants.items():
        plants.append(
            {
                "key": key,
                "name": unit.profile.name,
                "temperature": round(unit.state.temperature, 1),
                "air_humidity": round(unit.state.air_humidity, 1),
                "soil_moisture": round(unit.state.soil_moisture, 1),
                "light_level": unit.state.light_level,
                "light_today": unit.state.light_today,
                "growth_score": round(unit.state.growth_score, 1),
                "status": unit.state.status,
                "flowering_prediction": unit.state.flowering_prediction,
                "fruiting_prediction": unit.state.fruiting_prediction,
                "pump_on": unit.devices.pump_on,
                "lamp_on": unit.devices.lamp_on,
                "lamp_level": unit.devices.lamp_level,
                "fan_on": unit.devices.fan_on,
            }
        )

    return {
        "tick": greenhouse.tick,
        "minute_of_day": greenhouse.minute_of_day,
        "internet_ok": greenhouse.internet_ok,
        "fallback_mode": greenhouse.fallback_mode,
        "ai_enabled": greenhouse.ai_enabled,
        "water_tank_ok": greenhouse.water_tank_ok,
        "sensor_ok": greenhouse.sensor_ok,
        "power_ok": greenhouse.power_ok,
        "events": greenhouse.events[-10:],
        "plants": plants,
    }