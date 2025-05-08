# For more information, please refer to https://aka.ms/vscode-docker-python
FROM python:3.13-alpine

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Default environment variables
ENV RAIN3_POLL_INTERVAL=5
ENV MQTT_PORT=1883
ENV MQTT_TOPIC_BASE=rain3_00
ENV MQTT_DISCOVERY_IDENTIFIER=rain3_pump_001
ENV RAIN3_POLLMQTT_USERNAME_INTERVAL=rain3
ENV USE_ENV_FILE=true
ENV DEBUG_LEVEL=10

# Install pip requirements
COPY requirements.txt .
RUN python -m pip install -r requirements.txt

# Copy the project files over
WORKDIR /app
COPY main.py /app
COPY entities.json /app

# Creates a non-root user with an explicit UID and adds permission to access the /app folder
# For more info, please refer to https://aka.ms/vscode-docker-python-configure-containers
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

# During debugging, this entry point will be overridden. For more information, please refer to https://aka.ms/vscode-docker-python-debug
CMD ["python", "main.py"]
