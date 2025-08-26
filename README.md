> [!WARNING]  
> I am no longer actively maintaining this repository.
> 
> Development is now focused on a [“native” integration](https://github.com/official-Cromatin/ha-wilo).

> [!IMPORTANT]
> This software is developed for my own personal use and published for others to get inspired.
> Therefore "easy" integration in your setup might not be given and some changes needed.
> 
> ~~Please feel free to open issues if you encounter problems or have suggestions!~~


# Motivation
For a long time I wanted to integrate our domestic waterworks into something more manageable.
I have been running my own [Home Assistant](https://www.home-assistant.io/) instance for some time now and decided to develop an integration.

The aim is to display and record sensor data, alarms and setting parameters in Home Assistant and send notifications to my smartphone when an alarm is triggered.


# How it works
The processing pipeline is divided into several steps:

1. Loading the data from the HTTP endpoints
The web interface is periodically supplied with new data via 5 endpoints:
- `/identity`: Software version and equipment number
- `/state`: Live data on the status (runtime of the pump and fill level of the cistern)
- `/setup`: Long-term statistics (switch-on cycles, operating time)
- `/errors`: Current and historical errors
- `/installation`: Installation parameters (cistern shape and size)
- `/settings`: Operating parameters (switch-on and switch-off threshold pressure)
- `/download`: Connected Wifi network and IP address
These end points are queried by the program at the set time interval

2. Parsing the data
The loaded data is in HTML format and is first converted into a Python dictionary by the parser.

3. Identifying the changes
The program compares the data of the last status with the current status and thus detects differences

4. Transmitting the changes to HA via MQTT
Changes are converted to the correct format and sent to Home Assistant via the appropriate topic


# Installation and setup
1. Build the image
```bash
docker build -t rain3-integration .
```

2. Start the container
```bash
docker run -d \
  --name rain3 \
  -e USE_ENV_FILE=false
  -e DEBUG_LEVEL=10
  -e RAIN3_HOST=http://192.168.6.3
  -e RAIN3_POLL_INTERVAL=60
  -e MQTT_HOST=192.168.2.104
  -e MQTT_PORT=1883
  -e MQTT_TOPIC_BASE=rain3_00
  -e MQTT_DISCOVERY_IDENTIFIER=rain3_pump_001
  -e MQTT_USERNAME=rain3
  -e MQTT_PASSWORD=unwashed-powdering-budget
  rain3-integration
```

3. Environment variables

| Variable                    | Description                                        | Required  | Default |
| --------------------------- | -------------------------------------------------- | --------- | ------- |
| `USE_ENV_FILE`              | Disables the import of the .env file               | no        | `true`  |
| `DEBUG_LEVEL`               | Used debug level to print messages to the console  | no        | `20`    |
| `RAIN3_HOST`                | URL at which the rain3 webserver is reachable      | yes       | –       |
| `RAIN3_POLL_INTERVAL`       | Sampling rate                                      | yes       | `60`    |
| `MQTT_HOST`                 | MQTT host                                          | yes       | –       |
| `MQTT_PORT`                 | MQTT port                                          | yes       | `1883`  |
| `MQTT_TOPIC_BASE`           | MQTT topic base to use                             | yes       | –       |
| `MQTT_DISCOVERY_IDENTIFIER` | MQTT identifier used for discovery messages        | yes       | -       |
| `MQTT_USERNAME`             | MQTT username (if authentication is required)      |           | –       |
| `MQTT_PASSWORD`             | MQTT password (if authentication is required)      |           | –       |

# Contributing
If you find any bugs or have feature requests, feel free to open an issue or submit a pull request! 

Contributions are always welcome.


# License
This project is licensed under the MIT License - see the LICENSE file for details.
