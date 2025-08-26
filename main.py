import asyncio
import aiohttp
import aiohttp.client_exceptions
import aiohttp.web_exceptions
import gmqtt
import json
import logging
import dotenv
import os
from datetime import datetime
from colorama import Style, Fore
from typing import Any
from bs4 import BeautifulSoup
import re
import traceback
import signal

# Configure logging
class Colored_Formatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt='%Y-%m-%d %H:%M:%S', style='%'):
        super().__init__(fmt, datefmt, style)
        
    def format(self, record):
        date = f"{Style.BRIGHT}{Fore.BLACK}{self.formatTime(record, self.datefmt)}{Style.RESET_ALL}"
        levelname_color = {
            'DEBUG': Fore.CYAN,
            'INFO': Fore.BLUE,
            'WARNING': Fore.YELLOW,
            'ERROR': Fore.RED,
            'CRITICAL': f"{Style.BRIGHT}{Fore.RED}"
        }

        levelname = f"{levelname_color.get(record.levelname, Fore.WHITE)}{record.levelname:<8}{Fore.RESET}{Style.RESET_ALL}"
        name = f"{Fore.MAGENTA}{record.name:<10}{Fore.RESET}"
        message = record.getMessage()
        
        formatted_record = f"{date} {levelname} {name} {message}"
        return formatted_record

console_debug_level_env = os.getenv("DEBUG_LEVEL")
if console_debug_level_env:
    console_debug_level = logging.DEBUG
else:
    console_debug_level = logging.DEBUG
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(Colored_Formatter())

app_logger = logging.getLogger("app")
app_logger.addHandler(console_handler)
app_logger.setLevel(logging.DEBUG)

web_logger = logging.getLogger("web")
web_logger.addHandler(console_handler)
web_logger.setLevel(logging.DEBUG)

detector_logger = logging.getLogger("detector")
detector_logger.addHandler(console_handler)
detector_logger.setLevel(logging.DEBUG)

mqtt_logger = logging.getLogger("mqtt")
mqtt_logger.addHandler(console_handler)
mqtt_logger.setLevel(logging.DEBUG)

app_logger.info("Starting Rain3-HA-Integration")
app_logger.info(f"Using '{os.path.dirname(os.path.realpath(__file__))}' as entrypoint")

# Define functions
def get_elapsed_time_smal(before:datetime, now:datetime) -> str:
    """Convert an timestamp into an predefined elapsed time format (00sec 000ms)"""
    time_elapsed = datetime.fromtimestamp(now.timestamp() - before.timestamp())
    return f"{time_elapsed.second:02}sec {time_elapsed.microsecond // 1000:03}ms"

def replace_placeholder(payload: dict[str, Any] | str, placeholder_replacement: dict[str, Any], recursive: bool = False):
    for key in payload:
        value = payload[key]
        if isinstance(value, dict) and recursive:
            replace_placeholder(value, placeholder_replacement, recursive)
        elif isinstance(value, list) and recursive:
            index = 0
            for item in value:
                if isinstance(item, dict):
                    replace_placeholder(item, placeholder_replacement, recursive)
                elif isinstance(item, str):
                    for placeholder, replacement in placeholder_replacement.items():
                        item = item.replace("{" + placeholder + "}", str(replacement))
                    value[index] = item
                index += 1
        elif isinstance(value, str):
            for placeholder, replacement in placeholder_replacement.items():
                value = value.replace("{" + placeholder + "}", str(replacement))
            payload[key] = value
    return payload

async def establish_mqtt_connection(identifier:str) -> gmqtt.Client:
    mqtt_logger.info("Connecting to mqtt broker")
    before = datetime.now()

    # Load from config file
    if not os.getenv("MQTT_CLIENT_ID"):
        mqtt_logger.warning("Optional mqtt client id ('MQTT_CLIENT_ID') is missing")
        mqtt_client_id = None
    else:
        mqtt_client_id = os.getenv("MQTT_CLIENT_ID")
    client = gmqtt.Client(
        client_id = mqtt_client_id, 
        logger = mqtt_logger,
        will_message = gmqtt.Message(
            topic = f"homeassistant/binary_sensor/{identifier}_integration_active/state",
            payload = False,
            qos = 1,
            retain = True
        ))

    # Check if authentication is required
    if os.getenv("MQTT_USERNAME") or os.getenv("MQTT_PASSWORD"):
        if os.getenv("MQTT_USERNAME") and os.getenv("MQTT_PASSWORD"):
            client.set_auth_credentials(
                username = os.getenv("MQTT_USERNAME"),
                password = os.getenv("MQTT_PASSWORD")
            )
        else:
            mqtt_logger.warning("Only half of the authentication credentials are provided")

    # Try to establish connection
    try:
        await client.connect(
            host = os.getenv("MQTT_HOST"),
            port = int(os.getenv("MQTT_PORT"))
        )
    except ConnectionRefusedError as error:
        if error.errno == 61:
            mqtt_logger.critical("Unable to connect to mqtt broker, connection failed. Check adress and port and try again")
            quit(67)
        else:
            raise error
    except gmqtt.MQTTConnectError as error:
        if error._code == 134:
            mqtt_logger.critical("Invalid login credentials")
            quit(128)

    mqtt_logger.info(f"Connection successfully established to mqtt broker after {get_elapsed_time_smal(before, datetime.now())}")

    return client

async def enroll_entities(mqtt_client:gmqtt.Client, identifier:str):
    device_data = entities_data["device"]
    for sensor_config in entities_data["sensors"]:
        discovery_payload = sensor_config["discovery"]
        discovery_payload["device"] = device_data
        discovery_topic = sensor_config["discovery_topic"]

        mqtt_client.publish(discovery_topic, json.dumps(discovery_payload), qos = 1, retain = True)

    # Change integration state to on
    mqtt_client.publish(
        f"homeassistant/binary_sensor/{identifier}_integration_active/state",
        payload=True,
        retain=True,
        qos=0
    )

async def get_and_pase_website(url:str) -> dict | int | aiohttp.client_exceptions.ClientConnectionError:
    # Get content from url
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    web_logger.error(f"Failed to load '{url}' got {response.status}")
                    return response.status
                content = await response.text()
    except aiohttp.client_exceptions.ClientConnectionError as error:
        web_logger.error("Encountered error while reading website")
        traceback.print_exception(type(error), error, error.__traceback__)
        return error

    # Parse content and return
    soup = BeautifulSoup(content.replace('\x00', ''), 'html.parser')
    data = {}
    spans = soup.find_all('span')

    for span in spans:
        label = span.get_text(strip=True).rstrip(':')

        # Starte bei span und iteriere durch alle Geschwister
        next_node = span.next_sibling
        value = ""

        while next_node:
            # Wenn wir einen Zeilenumbruch erreichen, beenden wir die Schleife
            if next_node.name == 'span':
                break

            # Werte aus <b>-Tags oder anderen Textknoten holen
            if getattr(next_node, 'name', None) == 'b':
                value_part = next_node.get_text(strip=True)
                value += value_part
            elif isinstance(next_node, str):
                value += next_node.strip()

            next_node = next_node.next_sibling

        # Wert bereinigen und speichern, wenn vorhanden
        if value:
            value = value.replace('\n', '').strip()
            data[label] = value
    return data

async def update_states(mqtt_client:gmqtt.Client, last_states:dict, identifier:str):
    # Get the new states
    current_states = {}
    host = os.getenv("RAIN3_HOST")
    web_state = {"status": True}
    for url_path in ["/identity", "/state", "/setup", "/errors", "/installation", "/settings", "/download"]:
        before = datetime.now()

        data = await get_and_pase_website(f"{host}{url_path}")
        if isinstance(data, dict):
            current_states.update(data)
            web_state[url_path.strip("/")] = get_elapsed_time_smal(before, datetime.now())
        elif isinstance(data, aiohttp.client_exceptions.ClientConnectionError):
            web_state[url_path.strip("/")] = f"Encountered exception: {data.args}"
            web_state["status"] = False
        else:
            web_state[url_path.strip("/")] = f"Web error, code: {data}"
            web_state["status"] = False

    # Compare the old and new states
    for key in current_states:
        current_value:str = current_states[key]
        last_value = last_states.get(key)
        if current_value != last_value:
            detector_logger.debug(f"Value of '{key}' changed. {last_value} -> {current_value}")

            # Look up what entity coresponds to the content on the website
            index = entities_data["website_map"].get(key)
            if index == None:
                continue

            update_topic = entities_data["sensors"][index]["discovery"]["state_topic"]
            match key:
                case "MP":
                    update_payload = {"state": True if current_value == "ON" else False}

                case "MP running for":
                    match = re.fullmatch(r'(?:(\d+)min)?(?:(\d+)s)?', current_value)
                    
                    minutes = int(match.group(1)) if match.group(1) else 0
                    seconds = int(match.group(2)) if match.group(2) else 0
                    update_payload = {"runtime": round((minutes * 60 + seconds) / 60, 2)}

                case "Pressure":
                    normalized = current_value.replace(',', '.')
                    match = re.search(r'\d+(\.\d+)?', normalized)
                    update_payload = {"pressure": float(match.group())}

                case "3 Ways-valve":
                    if current_value == "Tap water":
                        state = "Tap"
                    else:
                        state = "Cistern"
                    update_payload = {"state": state}

                case "3.06 3-way valve mode":
                    if current_value == "Auto":
                        mode = "Auto"
                    else:
                        mode = "Manual"
                    update_payload = {"mode": mode}

                case "Level":
                    match = re.search(r'\d+(\.\d+)?', current_value)
                    update_payload = {"level": int(match.group())}

                case "Pump switches/hour":
                    match = re.match(r'(\d+)[/](\d+)', current_value)
                    update_payload = {
                        "starts": int(match.group(1)),
                        "limit": int(match.group(2))
                    }
                    is_json = True

                case "4.12 System":
                    match = re.search(r'(\d+)', current_value)
                    update_payload = {"runtime": int(match.group())}

                case "4.18 MP switches":
                    update_payload = {"switches": int(current_value)}

                case "4.13 MP":
                    match = re.fullmatch(r'(?:(\d+)h)?(?:\s*(\d+)min)?', current_value)
                    hours = int(match.group(1)) if match.group(1) else 0
                    minutes = int(match.group(2)) if match.group(2) else 0
                    update_payload = {"runtime": round(hours + (minutes / 60), 2)}
                    
    #         mqtt_client.publish(update_topic, json.dumps(update_payload), qos = 0)

    # mqtt_client.publish(
    #     f"homeassistant/sensor/{identifier}_last_update/state",
    #     payload = datetime.now().timestamp(),
    #     qos=0
    # )

    # mqtt_client.publish(
    #     f"homeassistant/binary_sensor/{identifier}_pump_connection/state",
    #     payload = json.dumps(web_state),
    #     qos = 0
    # )
    
    return current_states

async def cleanup_and_exit(signal:signal.Signals, mqtt_client:gmqtt.Client, identifier:str):
    app_logger.info("Signal received, shutting down...")

    mqtt_client.publish(
        f"homeassistant/binary_sensor/{identifier}_integration_active/state",
        False,
        1,
        True
    )

    await mqtt_client.disconnect()
    exit(0)

async def main(identifier):
    last_states = {}

    # Establish connection to mqtt broker
    # mqtt_client = await establish_mqtt_connection(identifier)

    # # Send discovery messages to ha
    # await enroll_entities(mqtt_client, identifier)

    # # Set up signal handlers for graceful shutdown
    # loop = asyncio.get_event_loop()
    # loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(cleanup_and_exit(signal.SIGINT, mqtt_client, identifier)))
    # loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(cleanup_and_exit(signal.SIGTERM, mqtt_client, identifier)))

    while True:
        last_states = await update_states(None, last_states, identifier)

        await asyncio.sleep(int(os.getenv("RAIN3_POLL_INTERVAL")))
    

# Entrypoint
if __name__ == '__main__':
    # Load config
    if bool(os.getenv("USE_ENV_FILE", True)) is False:
        if os.path.exists(".env"):
            app_logger.debug(".env file exists")
        else:
            app_logger.critical("No .env file found, aborting startup")
            quit(78)
        if os.path.getsize(".env") == 0:
            app_logger.critical(".env file is empty")
            quit(78)
        dotenv.load_dotenv(override=True)
    else:
        app_logger.info("")

    # Check each required parameter
    missing_envs:list[str] = []
    for env_name in ["RAIN3_HOST", "RAIN3_POLL_INTERVAL", "MQTT_HOST", "MQTT_PORT", "MQTT_TOPIC_BASE"]:
        if not os.getenv(env_name):
            missing_envs.append(env_name)

    if len(missing_envs) > 0:
        app_logger.critical(f"Required parameters of the .env file are missing (see .example_env), missing: {", ".join(missing_envs)}")
        quit(78)

    # Open entities file
    entities_data = json.load(open("entities.json"))

    # and replace the data
    topic_base = os.getenv("MQTT_TOPIC_BASE")
    if os.getenv("MQTT_DISCOVERY_IDENTIFIER") is None:
        app_logger.warning("Optional discovery identifier 'MQTT_DISCOVERY_IDENTIFIER' is missing, defaulting to 'MQTT_TOPIC_BASE'")
        device_identifier = topic_base
    else:
        device_identifier = os.getenv("MQTT_DISCOVERY_IDENTIFIER")
    entities_data = replace_placeholder(
        entities_data,
        {
            "topic_base": topic_base,
            "identifier": device_identifier
        },
        True
    )

    asyncio.run(main(device_identifier))