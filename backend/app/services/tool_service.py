from __future__ import annotations

import ast
import operator
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx


WEATHER_CODE_MAP = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
}

TIMEZONE_HINTS = {
    "pakistan": "Asia/Karachi",
    "karachi": "Asia/Karachi",
    "lahore": "Asia/Karachi",
    "faisalabad": "Asia/Karachi",
    "sialkot": "Asia/Karachi",
    "utc": "UTC",
    "london": "Europe/London",
    "new york": "America/New_York",
    "dubai": "Asia/Dubai",
}

ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class ToolServiceError(ValueError):
    pass


class ToolService:
    def extract_expression(self, query: str) -> str:
        candidate = re.sub(r"[^0-9+\-*/().% ]", " ", query)
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if not candidate or not re.search(r"\d", candidate):
            raise ToolServiceError("No calculator expression was found in the query.")
        return candidate

    def _evaluate_ast(self, node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return self._evaluate_ast(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPERATORS:
            left = self._evaluate_ast(node.left)
            right = self._evaluate_ast(node.right)
            return float(ALLOWED_OPERATORS[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_OPERATORS:
            operand = self._evaluate_ast(node.operand)
            return float(ALLOWED_OPERATORS[type(node.op)](operand))
        raise ToolServiceError("Unsupported calculator expression.")

    def run_calculator(self, query: str) -> dict:
        expression = self.extract_expression(query)
        parsed = ast.parse(expression, mode="eval")
        result = self._evaluate_ast(parsed)
        return {
            "tool_name": "calculator",
            "expression": expression,
            "result": round(result, 6),
        }

    def run_time_lookup(self, query: str) -> dict:
        lowered = query.lower()
        timezone_name = next((value for key, value in TIMEZONE_HINTS.items() if key in lowered), "Asia/Karachi")
        now = datetime.now(ZoneInfo(timezone_name))
        return {
            "tool_name": "time",
            "timezone": timezone_name,
            "local_time": now.isoformat(),
            "utc_time": datetime.now(UTC).isoformat(),
        }

    async def run_weather_lookup(self, query: str) -> dict:
        match = re.search(r"(?:weather|temperature|forecast)(?:\s+in|\s+for|\s+at)?\s+(.+)", query, re.IGNORECASE)
        location = match.group(1).strip(" ?.,") if match else ""
        if not location:
            raise ToolServiceError("Please specify a city or location for the weather lookup.")

        async with httpx.AsyncClient(timeout=15) as client:
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": location, "count": 1, "language": "en", "format": "json"},
            )
            geo.raise_for_status()
            geo_payload = geo.json()
            results = geo_payload.get("results") or []
            if not results:
                raise ToolServiceError(f"No weather location match was found for '{location}'.")
            place = results[0]

            weather = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
                },
            )
            weather.raise_for_status()
            current = weather.json().get("current", {})

        weather_code = current.get("weather_code")
        return {
            "tool_name": "weather",
            "location": f"{place['name']}, {place.get('country', '')}".strip(", "),
            "temperature_c": current.get("temperature_2m"),
            "apparent_temperature_c": current.get("apparent_temperature"),
            "humidity_percent": current.get("relative_humidity_2m"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
            "summary": WEATHER_CODE_MAP.get(weather_code, "Current weather available"),
        }

    async def invoke(self, tool_name: str, query: str) -> dict:
        if tool_name == "calculator":
            return self.run_calculator(query)
        if tool_name == "time":
            return self.run_time_lookup(query)
        if tool_name == "weather":
            return await self.run_weather_lookup(query)
        raise ToolServiceError(f"Unsupported tool '{tool_name}'.")
