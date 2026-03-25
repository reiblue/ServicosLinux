# -*- coding: utf-8 -*-
# Módulo SmartLab (engine-compatible)
# autor: Rodrigo Mendes Peixoto
# versão: 1.0.9 (moduleized)
# Last update: 2026-03-23

import json
import threading
import time
import logging
import sys
import os
from typing import Final, Optional
from datetime import datetime, time as dtime, timedelta

import paho.mqtt.client as mqtt


MODULE_NAME: Final = "dt_smartLaboratory"
VERSION: Final = "1.0.9"
LAST_UPDATE: Final = "2026-03-23"
SYSTEM_DESCRIPTION: Final = (
    "Gerenciamento de Laboratório Smart Lab\n"
    "Sistema Smart Lab para gerenciamento de laboratório computacional com 20 computadores, \n"
    "integrando sensores de temperatura e controle de ar-condicionado, monitoramento de energia elétrica, \n"
    "estado da porta e acionamento de relés, utilizando comunicação MQTT para automação \n"
    "e eficiência energética."
)

# ========= LOGGER (não reconfigura logging global do app) =========
logger = logging.getLogger(MODULE_NAME)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


# ========= CONFIG (valores padrão; pode sobrescrever via context) =========
BROKER_HOST = "10.11.4.111"
#BROKER_HOST = "192.168.100.52"
BROKER_PORT = 8883
KEEPALIVE   = 60

TOPIC_COMPUTER_KEEPALIVE  = r"C102/SHUTDOWN_COMPUTER"
TOPIC_AIR   = "C102/AR_CONDICIONADO"
TOPIC_RETURN_AIR = "C102/AIR"
TOPIC_AM2302 = "C102/AM2302"
TOPIC_ENERGY = "C102/ENERGY_MONITOR"
TOPIC_STATUS_RELES = "C102/RELES"
TOPIC_DOOR_OPEN = "C102/DOOR_STATUS"
TOPIC_STATUS_LABORATOY = "C102/STATUS_LABORATORY"
TOPIC_PROCESS_COMPUTERS = "C102/PROCESS_COMPUTERS"
TOPIC_SENSORS = "C102/HARDWARE_SENSORS"

TEMP_AIR_LEFT = 23
TEMP_AIR_RIGHT = 23
TIME_SLEEP = 60
TIME_WAIT_COMPUTER_OFF = 7  # minutos

IDLE_MINUTES = 7
MIN_TEMP_ON = 25.0
MIN_TEMP_OFF = 20.0
MIN_ENERGY = 0.1  # kwh


# ========= CERT PATH (padrão; pode sobrescrever via context) =========
def default_ca_path() -> str:
    if sys.platform == "win32":
        # deixe um padrão “seguro”; você pode sobrescrever no context
        #certificate_ca = r"C:\Users\Peixoto\Documents\Pós-Graduações\Mestrado\UFJF - Computação\Pesquisa\certs\notebook.crt"
        certificate_ca = r"C:\Program Files\SmartClassroom\ca.crt"
        return certificate_ca
    if sys.platform.startswith("linux"):
        return "/home/csti/ca.crt"
    return "/home/csti/ca.crt"


# ========= ESTADO GLOBAL DO MÓDULO (mantém seu comportamento) =========
certificate_ca = ""
LABORATORY_SHUTDOWN = False
DOOR_STATUS = "NONE"

last_any_msg = datetime.min
air_state_left = "off"
air_state_right = "off"
last_temp = 29.0
last_temp_ts = None
last_temp_external = None
last_energy = 0.0

lock = threading.Lock()

_client: Optional[mqtt.Client] = None
_watchdog_stop_event: Optional[threading.Event] = None
_watchdog_thread: Optional[threading.Thread] = None


class Computador:
    def __init__(self, name: str, side: str):
        self.name = name
        self.side = side
        self.processes: Optional[bytes] = None
        self.sensors: Optional[bytes] = None
        self.lastActivity = datetime.now()
        self._last_ts = time.monotonic() - timedelta(days=1).total_seconds()

    def touch(self):
        self.lastActivity = datetime.now()
        self._last_ts = time.monotonic()

    def updateDateTime(self):
        self.lastActivity = datetime.now()
        self._last_ts = time.monotonic()

    def is_stale(self, minutes: int = 1) -> bool:
        elapsed = time.monotonic() - self._last_ts
        return elapsed >= minutes * 60

    def shutdownComputer(self):
        self._last_ts = time.monotonic() - timedelta(days=1).total_seconds()

    def setProcesses(self, payload: bytes) -> None:
        self.processes = payload

    def setSensors(self, payload: bytes) -> None:
        self.sensors = payload


SIDE_LEFT = {
    "CEPF-C102-C02","CEPF-C102-C03","CEPF-C102-C06","CEPF-C102-C07","CEPF-C102-C08",
    "CEPF-C102-C11","CEPF-C102-C12","CEPF-C102-C15","CEPF-C102-C16","CEPF-C102-C19","CEPF-C102-C20"
}
SIDE_RIGHT = {
    "CEPF-C102-C01","CEPF-C102-C04","CEPF-C102-C05","CEPF-C102-C09","CEPF-C102-C10",
    "CEPF-C102-C13","CEPF-C102-C14","CEPF-C102-C17","CEPF-C102-C18",
}

if sys.platform == "win32":
    SIDE_RIGHT.add("DESK-DELL-C01")
    SIDE_LEFT.add("CEPF-C102-V02")

computers_left: dict[str, Computador] = {pc: Computador(pc, "LEFT") for pc in SIDE_LEFT}
computers_right: dict[str, Computador] = {pc: Computador(pc, "RIGHT") for pc in SIDE_RIGHT}


# ========= HELPERS MQTT =========
def send_air(client: mqtt.Client, command: str):
    client.publish(TOPIC_AIR, command + "\n", qos=0, retain=False)

def criar_json_shutdown(status: bool):
    return json.dumps({"SHUTDOWN": status})

def sendMqttCommand(client: mqtt.Client, topic: str, command: bool):
    client.publish(topic, criar_json_shutdown(command) + "\n", qos=0, retain=False)


def set_air_on_if_needed(client: mqtt.Client, sideAir: str):
    global air_state_left, air_state_right, last_temp
    with lock:
        temp_ok = (last_temp is not None) and (last_temp >= MIN_TEMP_ON) and (MIN_TEMP_OFF <= last_temp)
        if not temp_ok:
            logger.info(f"Bloqueado LIGAR: temperatura={last_temp} (min_off={MIN_TEMP_OFF}, min_on={MIN_TEMP_ON})")
            return

        if sideAir == "LEFT" and air_state_left != "on":
            send_air(client, f"LIGAR_23_{sideAir}")
            logger.info(f"[CMD] -> {TOPIC_AIR} = LIGAR_23_{sideAir}")
        elif sideAir == "RIGHT" and air_state_right != "on":
            send_air(client, f"LIGAR_23_{sideAir}")
            logger.info(f"[CMD] -> {TOPIC_AIR} = LIGAR_23_{sideAir}")


def set_air_off_if_needed(client: mqtt.Client, sideAir: str):
    global air_state_left, air_state_right, last_temp

    with lock:
        if air_state_left == "off" and air_state_right == "off":
            return

        now = datetime.now()
        if now.time() >= dtime(18, 0) or now.time() < dtime(6, 0):
            logger.info("Fora do horário de uso do ar condicionado.")
            if air_state_left != "off":
                send_air(client, "DESLIGAR_LEFT")
                logger.info("[CMD] -> DESLIGAR_LEFT")
            if air_state_right != "off":
                send_air(client, "DESLIGAR_RIGHT")
                logger.info("[CMD] -> DESLIGAR_RIGHT")
            return

        temp_ok = (last_temp is not None) and (MIN_TEMP_OFF <= last_temp)
        if not temp_ok:
            send_air(client, "DESLIGAR_LEFT")
            send_air(client, "DESLIGAR_RIGHT")
            logger.info(f"[CMD] -> Desligar ambos por temperatura '{last_temp}'")
            return

        if sideAir == "LEFT" and air_state_left != "off":
            send_air(client, "DESLIGAR_LEFT")
            logger.info("[CMD] -> DESLIGAR_LEFT")
        elif sideAir == "RIGHT" and air_state_right != "off":
            send_air(client, "DESLIGAR_RIGHT")
            logger.info("[CMD] -> DESLIGAR_RIGHT")


# ========= WATCHDOG =========
def watchdog_loop(client: mqtt.Client, stop_event: threading.Event):
    global last_any_msg, air_state_left, air_state_right, last_temp_external, last_temp, last_energy, MIN_ENERGY
    global LABORATORY_SHUTDOWN

    while not stop_event.is_set():
        time.sleep(TIME_SLEEP)

        with lock:
            _ = datetime.now() - last_any_msg  # se quiser usar, já está aqui

        allLeft = True
        for pc in computers_left.values():
            if not pc.is_stale(TIME_WAIT_COMPUTER_OFF):
                allLeft = False
                break

        allRight = True
        for pc in computers_right.values():
            if not pc.is_stale(TIME_WAIT_COMPUTER_OFF):
                allRight = False
                break

        if allLeft and air_state_left != "off":
            set_air_off_if_needed(client, "LEFT")
            logger.info("Desligar ar esquerdo por inatividade")

        if allRight and air_state_right != "off":
            set_air_off_if_needed(client, "RIGHT")
            logger.info("Desligar ar direito por inatividade")

        if (not LABORATORY_SHUTDOWN) and allLeft and allRight:
            sendMqttCommand(client, "C102/STATUS", True)
            logger.info("Enviado comando de desligamento do laboratorio")

        if air_state_left == "off" and air_state_right == "off":
            if (last_energy > MIN_ENERGY) and allLeft and allRight:
                send_air(client, "DESLIGAR_RIGHT")
                send_air(client, "DESLIGAR_LEFT")
                logger.info(f"Bloqueado Desligar: consumo {last_energy} kwh > {MIN_ENERGY} kwh (resetando leitura)")
                last_energy = 0.0
            continue

        now = datetime.now()
        if (now.time() >= dtime(18, 0) or now.time() < dtime(6, 0)) and (air_state_left != "off" or air_state_right != "off"):
            logger.info("Fora do horário de uso do ar condicionado.")
            if air_state_left != "off":
                send_air(client, "DESLIGAR_LEFT")
            if air_state_right != "off":
                send_air(client, "DESLIGAR_RIGHT")
            continue
        else:
            if (last_temp_external is not None) and (last_temp is not None) and last_temp_external < last_temp and last_temp < MIN_TEMP_ON:
                logger.info(f"Temp externa ({last_temp_external}) < interna ({last_temp}). Desligando ar.")
                if air_state_left != "off":
                    send_air(client, "DESLIGAR_LEFT")
                if air_state_right != "off":
                    send_air(client, "DESLIGAR_RIGHT")
                continue


# ========= PARSER =========
def parse_temperature(payload) -> float | None:
    try:
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8", errors="ignore")

        if isinstance(payload, str) and payload.strip().startswith(("{", "[")):
            obj = json.loads(payload)
        else:
            obj = payload

        if isinstance(obj, dict):
            for k in ("TEMPERATURE", "temperature", "temp", "Temperature"):
                if k in obj:
                    v = obj[k]
                    try:
                        return float(v)
                    except:
                        return None
            if "sensors" in obj and isinstance(obj["sensors"], list):
                for s in obj["sensors"]:
                    name = (s.get("name") or s.get("Name") or "").lower()
                    if "temp" in name or "am2302" in name or "dht" in name:
                        try:
                            return float(s.get("value") or s.get("Value"))
                        except:
                            pass
            return None

        if isinstance(obj, str):
            try:
                return float(obj.strip().replace(",", "."))
            except:
                return None

        if isinstance(obj, (int, float)):
            return float(obj)

        return None
    except Exception:
        return None


# ========= CALLBACKS =========
def on_connect(client, userdata, flags, rc, properties=None):
    logger.info(f"Conectado ao broker, rc={rc}")
    client.subscribe(TOPIC_COMPUTER_KEEPALIVE)
    client.subscribe(TOPIC_AM2302)
    client.subscribe(TOPIC_ENERGY)
    client.subscribe(TOPIC_STATUS_RELES)
    client.subscribe(TOPIC_DOOR_OPEN)
    client.subscribe(TOPIC_RETURN_AIR)
    client.subscribe(TOPIC_STATUS_LABORATOY)
    client.subscribe(TOPIC_PROCESS_COMPUTERS)
    client.subscribe(TOPIC_SENSORS)

    logger.info("Sistema iniciado. Solicitando informações iniciais...")
    client.publish("C102/DOOR", "\n", qos=0, retain=False)
    sendMqttCommand(client, "C102/STATUS", True)


def on_message(client, userdata, msg):
    global last_any_msg, last_temp, last_temp_ts, last_temp_external, last_energy
    global air_state_left, air_state_right, DOOR_STATUS, LABORATORY_SHUTDOWN, TIME_WAIT_COMPUTER_OFF, TOPIC_STATUS_LABORATOY

    topic = msg.topic
    payload_raw = msg.payload

    try:
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception:
        payload = None

    if payload is None:
        return

    if topic == TOPIC_COMPUTER_KEEPALIVE:
        with lock:
            last_any_msg = datetime.now()

        computer = payload.get("COMPUTER_NAME") or payload.get("Computer")
        if not computer:
            return

        action = payload.get("ACTION")

        logger.info(f"Keepalive recebido do computador: {computer} ação={action}")

        if computer in SIDE_LEFT:
            if action == "KEETALIVE":
                computers_left[computer].updateDateTime()
                set_air_on_if_needed(client, "LEFT")
            elif action == "SHUTDOWN":
                computers_left[computer].shutdownComputer()
        else:
            if action == "KEETALIVE":
                computers_right[computer].updateDateTime()
                set_air_on_if_needed(client, "RIGHT")
            elif action == "SHUTDOWN":
                computers_right[computer].shutdownComputer()

    elif topic == TOPIC_AM2302:
        temp = parse_temperature(payload_raw)
        located = payload.get("LOCATED")
        if temp is not None and located == "C102":
            with lock:
                last_temp = temp
                last_temp_ts = datetime.now()
            logger.info(f"Temperatura interna atualizada: {last_temp}")
        elif temp is not None and located == "EXTERNO_CSTI":
            with lock:
                last_temp_external = temp
            logger.info(f"Temperatura externa atualizada: {last_temp_external}")

    elif topic == TOPIC_ENERGY:
        energy = payload.get("KWH")
        if energy is not None:
            with lock:
                last_energy = energy
            logger.info(f"Consumo energia atualizado: {last_energy} kwh")

    elif topic == TOPIC_STATUS_RELES:
        shutdown = payload.get("VALUE")
        LABORATORY_SHUTDOWN = not shutdown
        logger.info(f"Status desligamento laboratório: {LABORATORY_SHUTDOWN}")

    elif topic == TOPIC_DOOR_OPEN:
        door_status = payload.get("STATUS")
        if door_status == "OPEN":
            LABORATORY_SHUTDOWN = False
            DOOR_STATUS = "OPEN"
            logger.info("Porta aberta. Reles acionados.")
        else:
            DOOR_STATUS = "CLOSED"
            logger.info("Porta fechada.")

    elif topic == TOPIC_RETURN_AIR:
        command = payload.get("COMMAND")
        if command is not None:
            air_state_left = str(payload.get("LEFT")).lower()
            air_state_right = str(payload.get("RIGHT")).lower()
            logger.info(f"Status ar atualizado: LEFT={air_state_left}, RIGHT={air_state_right}")

    elif topic == TOPIC_STATUS_LABORATOY:
        status = {
            "DOOR": DOOR_STATUS,
            "TEMPERATURE": last_temp,
            "TEMPERATURE_EXTERNAL": last_temp_external,
            "AIR_LEFT": air_state_left,
            "AIR_RIGHT": air_state_right,
            "ENERGY_KWH": last_energy,
            "LABORATORY_SHUTDOWN": LABORATORY_SHUTDOWN
        }
        json_payload = json.dumps(status)
        client.publish("C102/LAST_STATUS", json_payload)

        for pc in computers_left.values():
            if not pc.is_stale(TIME_WAIT_COMPUTER_OFF):
                if pc.processes:
                    client.publish(TOPIC_PROCESS_COMPUTERS + "_request", pc.processes)
                if pc.sensors:
                    client.publish(TOPIC_SENSORS + "_request", pc.sensors)

        for pc in computers_right.values():
            if not pc.is_stale(TIME_WAIT_COMPUTER_OFF):
                if pc.processes:
                    client.publish(TOPIC_PROCESS_COMPUTERS + "_request", pc.processes)
                if pc.sensors:
                    client.publish(TOPIC_SENSORS + "_request", pc.sensors)

        logger.info(f"Status solicitado. Enviando: {json_payload}")

    elif topic == TOPIC_PROCESS_COMPUTERS:
        computer = payload.get("ComputerName") or payload.get("Computer")
        logger.info(f"Processos recebidos do computador: {computer}")
        if not computer:
            return
        if computer in SIDE_LEFT:
            computers_left[computer].setProcesses(payload_raw)
        elif computer in SIDE_RIGHT:
            computers_right[computer].setProcesses(payload_raw)

    elif topic == TOPIC_SENSORS:
        try:
            computer = payload[0].get("COMPUTER_NAME") or payload[0].get("Computer")
            logger.info(f"Processos recebidos do computador: {computer}")

            if not computer:
                return
            if computer in SIDE_LEFT:
                computers_left[computer].setSensors(payload_raw)
            elif computer in SIDE_RIGHT:
                computers_right[computer].setSensors(payload_raw)
        except Exception as e:
            logger.error(f"Erro ao processar sensores: {e}")


# ========= LIFECYCLE DO MÓDULO (ENGINE) =========
def setup(context: dict):
    """
    Aqui você prepara config e paths antes de rodar a thread.
    Você pode passar overrides via context["config"].
    """
    global certificate_ca, BROKER_HOST, BROKER_PORT, KEEPALIVE, TIME_SLEEP, TIME_WAIT_COMPUTER_OFF
    global MIN_TEMP_ON, MIN_TEMP_OFF, MIN_ENERGY
    global _client, _watchdog_stop_event, _watchdog_thread, last_any_msg

    cfg = (context.get("config") or {}).get("air_control_c102", {})

    BROKER_HOST = cfg.get("BROKER_HOST", BROKER_HOST)
    BROKER_PORT = int(cfg.get("BROKER_PORT", BROKER_PORT))
    KEEPALIVE = int(cfg.get("KEEPALIVE", KEEPALIVE))

    TIME_SLEEP = int(cfg.get("TIME_SLEEP", TIME_SLEEP))
    TIME_WAIT_COMPUTER_OFF = int(cfg.get("TIME_WAIT_COMPUTER_OFF", TIME_WAIT_COMPUTER_OFF))

    MIN_TEMP_ON = float(cfg.get("MIN_TEMP_ON", MIN_TEMP_ON))
    MIN_TEMP_OFF = float(cfg.get("MIN_TEMP_OFF", MIN_TEMP_OFF))
    MIN_ENERGY = float(cfg.get("MIN_ENERGY", MIN_ENERGY))

    certificate_ca = cfg.get("CA_CERT", "") or context.get("ca_cert") or default_ca_path()

    logger.info(SYSTEM_DESCRIPTION)
    logger.info(f"[setup] {MODULE_NAME} v{VERSION}")
    logger.info(f"[setup] broker={BROKER_HOST}:{BROKER_PORT} ca={certificate_ca}")

    logger.info("[run] iniciando MQTT...")

    client = mqtt.Client()
    _client = client

    # TLS
    if certificate_ca and os.path.exists(certificate_ca):
        client.tls_set(ca_certs=certificate_ca)
        client.tls_insecure_set(True)
        
        client.username_pw_set("python_user", "cst1!C3PF#2026@python")
    else:
        logger.warning(f"[run] CA cert não encontrado: {certificate_ca} (seguindo mesmo assim)")

    client.on_connect = on_connect
    client.on_message = on_message

     # Evita “desligar imediato” no boot
    with lock:
        last_any_msg = datetime.now()

    try_and_timeout = True
    
    while try_and_timeout:
        try:
            client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)
            try_and_timeout = False
        except Exception as e:
            logger.error(f"[run] erro ao conectar ao broker MQTT: {e}")
            
            if e and "timed out" not in str(e).lower():
                try_and_timeout = False  # Não tenta mais se for timeout
                
            time.sleep(30)  # Espera 5 segundos antes de tentar novamente
            
        

    # Watchdog
    _watchdog_stop_event = threading.Event()
    _watchdog_thread = threading.Thread(
        target=watchdog_loop,
        args=(client, _watchdog_stop_event),
        daemon=True
    )
    _watchdog_thread.start()

    client.loop_start()
    logger.info("[run] rodando (aguardando stop_event)...")

def run(stop_event: threading.Event, context: dict):  
    # Loop MQTT em background, e a thread do módulo fica “viva” aguardando stop_event    

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        logger.info("[run] stop_event recebido. Encerrando...")


def teardown(context: dict):
    """
    Finalização garantida pelo engine.
    """
    global _client, _watchdog_stop_event, _watchdog_thread

    logger.info("[teardown] parando watchdog e MQTT...")

    try:
        if _watchdog_stop_event is not None:
            _watchdog_stop_event.set()
        if _watchdog_thread is not None and _watchdog_thread.is_alive():
            _watchdog_thread.join(timeout=2)
    except Exception as e:
        logger.error(f"[teardown] erro ao parar watchdog: {e}")

    try:
        if _client is not None:
            _client.loop_stop()
            _client.disconnect()
    except Exception as e:
        logger.error(f"[teardown] erro ao desconectar MQTT: {e}")

    _client = None
    _watchdog_stop_event = None
    _watchdog_thread = None

    logger.info("[teardown] finalizado.")
