FROM python:3.13.9-slim
WORKDIR /bot
COPY mechfight.py pilot.py ./
USER 65534:65534
ENTRYPOINT ["python3","-Bu","/bot/pilot.py"]
