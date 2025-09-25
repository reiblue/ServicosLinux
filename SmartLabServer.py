# -*- coding: utf-8 -*-
# Requisitos: paho-mqtt já instalado (pip install paho-mqtt)
# autor: Rodrigo Mendes Peixoto
# email: rodrigo.peixoto@ifrj.edu.br
# data de criação: 2024-06-10
# data de modificação: 2024-09-25
# versão: 1.0.4
# descrição: Controla ar condicionado com base em atividade de computadores e temperatura ambiente.
# Observa mensagens MQTT em C102\PROCESS_COMPUTERS e C102/AM2302.
# Liga o ar se um computador ligar e a temperatura estiver alta.
# Desliga o ar se todos os computadores estiverem desligados por mais de 2 minutos

import json
import threading
import time
import logging
import sys
import paho.mqtt.client as mqtt
import sys
from datetime import datetime, time as dtime
from dataclasses import dataclass, field




logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)  # manda pro systemd
    ]
)

logger = logging.getLogger("SmartLabServer")

certificate_ca = ""

if sys.platform == "win32":        # Windows
    logger.info("rodando no Windows")
    certificate_ca = r"C:\Program Files\SmartClassroom\ca.crt"
elif sys.platform.startswith("linux"):  # Linux
    logger.info("rodando no Linux")
    certificate_ca = "/home/csti/ca.crt"
elif sys.platform == "darwin":     # macOS
    logger.info("rodando no macOS")
    certificate_ca = "/home/csti/ca.crt"


class Computador:
    
    def __init__(self, name: str, side: str):
        self.name = name
        self.side = side
        #self.lastActivity = datetime.now()
        self.lastActivity = datetime.now()
        self._last_ts = time.monotonic() - (1 * 60)

    def touch(self):
        self.lastActivity = datetime.now()
    def updateDateTime(self):
        self.lastActivity = datetime.now()
        self._last_ts = time.monotonic()
        #print(datetime.now())
    def is_stale(self, minutes: int = 1) -> bool:
        #print(time.monotonic() - self._last_ts)
        #print(self.lastActivity)
        return (time.monotonic() - self._last_ts) >= minutes * 60


# ========= CONFIG =========
BROKER_HOST = "10.11.102.123"
BROKER_PORT = 8883
KEEPALIVE   = 60

TOPIC_PROC  = r"C102\PROCESS_COMPUTERS"   # backslash mantido
TOPIC_AIR   = "C102/AR_CONDICIONADO"
TOPIC_AM2302 = "C102/AM2302"
TOPIC_ENERGY = "C102/ENERGY_MONITOR"
TEMP_AIR_LEFT = 23
TEMP_AIR_RIGHT = 23
TIME_SLEEP = 30



SIDE_LEFT = {
    "CEPF-C102-C02",
    "CEPF-C102-C03",
    "CEPF-C102-C06",
    "CEPF-C102-C07",
    "CEPF-C102-C08",
    "CEPF-C102-C12",
    "CEPF-C102-C15",
    "CEPF-C102-C16",
    "CEPF-C102-C19",
    "CEPF-C102-C20"
}
SIDE_RIGHT = {
    "CEPF-C102-C01",
    "CEPF-C102-C04",
    "CEPF-C102-C05",
    "CEPF-C102-C09",
    "CEPF-C102-C10",
    "CEPF-C102-C11",
    "CEPF-C102-C13",
    "CEPF-C102-C14",
    "CEPF-C102-C17",
    "CEPF-C102-C18",
}

computers_left: dict[str, Computador] = {}
computers_right: dict[str, Computador] = {}

for pc in SIDE_LEFT:
    computers_left[pc] = Computador(name=pc, side="LEFT")

for pc in SIDE_RIGHT:
    computers_right[pc] = Computador(name=pc, side="RIGHT")

IDLE_MINUTES = 2
MIN_TEMP_ON = 23.0   # condição para permitir Ligar_18
MIN_TEMP_OFF = 20.0
MIN_ENERGY =  0.1  # kwh, condição para permitir Ligar_18
# ========= ESTADO =========
last_any_msg = datetime.min
air_state_left = "unknown"        # "on" | "off" | "unknown"
air_state_right = "unknown"        # "on" | "off" | "unknown"
last_temp = None             # última TEMPERATURE recebida (float)
last_temp_ts = None
last_temp_external = None
last_energy = 0.0         # última ENERGY recebida (float)
lock = threading.Lock()

# ========= AÇÕES =========
def send_air(client: mqtt.Client, command: str):
    client.publish(TOPIC_AIR, command + "\n", qos=0, retain=False)

def set_air_on_if_needed(client: mqtt.Client, sideAir):
    """Liga somente se temperatura >= MIN_TEMP_ON."""
    global air_state_left, air_state_right, last_temp
    with lock:
        temp_ok = (last_temp is not None) and (last_temp >= MIN_TEMP_ON) and (MIN_TEMP_OFF <= last_temp)
        if not temp_ok:
            # Sem temperatura válida ou fora do limite — não liga
            logger.info(f"[INFO] Bloqueado Ligar_18: temperatura={last_temp} (entre {MIN_TEMP_OFF} e {MIN_TEMP_ON})")
            return
        
        if sideAir == "LEFT" and air_state_left != "on":            
            send_air(client, f"LIGAR_18_{sideAir}")
            logger.info(f"Status air: {air_state_left}")
            air_state_left = "on"
            logger.info(f"[CMD] -> C102/AIR = LIGAR_18_{sideAir}")
        elif sideAir == "RIGHT" and air_state_right != "on":
            send_air(client, f"LIGAR_18_{sideAir}")
            logger.info(f"Status air: {air_state_right}")
            air_state_right = "on"
            logger.info(f"[CMD] -> C102/AIR = LIGAR_18_{sideAir}")

def set_air_off_if_needed(client: mqtt.Client, sideAir):
    global air_state_left, air_state_right
    with lock:


        if air_state_left == "off" and air_state_right == "off":
            return
        
        now = datetime.now()
        if now.time() >= dtime(18, 0) or now.time() < dtime(6, 0):
            logger.info("Fora do horário de uso do ar condicionado.")
            if air_state_left != "off":
                send_air(client, f"DESLIGAR_LEFT")
                air_state_left = "off"
                logger.info(f"[CMD] -> C102/AIR = Desligar_LEFT")
            if air_state_right != "off":
                send_air(client, f"DESLIGAR_RIGHT")
                air_state_right = "off"
                logger.info(f"[CMD] -> C102/AIR = Desligar_RIGHT")
            return

        temp_ok = (last_temp is not None) and (MIN_TEMP_OFF >= last_temp)
        #desliga o ar se a temperatura for menor que MIN_TEMP_OFF
        if not temp_ok:
            send_air(client, f"DESLIGAR_LEFT")
            send_air(client, f"DESLIGAR_RIGHT")
            air_state_left = "off"
            air_state_right = "off"
            logger.info(f"[CMD] -> C102/AIR = Desligar ambos os lados por temperatura '{last_temp}' ou por atividade inicial")
            return
        
        if sideAir == "LEFT":
            if air_state_left != "off":
                send_air(client, f"DESLIGAR_{sideAir}")
                air_state_left = "off"
                logger.info(f"[CMD] -> C102/AIR = Desligar_{sideAir}")
        else:
            if air_state_right != "off":
                send_air(client, f"DESLIGAR_{sideAir}")
                air_state_right = "off"
                logger.info(f"[CMD] -> C102/AIR = Desligar_{sideAir}")
        

# ========= WATCHDOG =========
def watchdog_thread(client: mqtt.Client, stop_event: threading.Event):
    global last_any_msg, air_state_left, air_state_right, last_temp_external, last_temp, last_energy, MIN_ENERGY
    while not stop_event.is_set():
        time.sleep(TIME_SLEEP)
        with lock:
            idle = datetime.now() - last_any_msg
        

        if air_state_left == "off" and air_state_right == "off":
            if(last_energy > MIN_ENERGY):
                send_air(client, f"DESLIGAR_RIGHT")
                send_air(client, f"DESLIGAR_LEFT")
                logger.info(f"[INFO] Bloqueado Desligar: consumo de energia {last_energy} kwh maior que {MIN_ENERGY} kwh")
                last_energy = 0.0
            continue  # ambos os ares desligados, nada a fazer

            
        
        now = datetime.now()
        if (now.time() >= dtime(18, 0) or now.time() < dtime(6, 0)) and (air_state_left != "off" or air_state_right != "off"):
            logger.info("Fora do horário de uso do ar condicionado.")
            if air_state_left != "off":
                send_air(client, f"DESLIGAR_LEFT")
                air_state_left = "off"
                logger.info(f"[CMD] -> C102/AIR = Desligar_LEFT")
            if air_state_right != "off":
                send_air(client, f"DESLIGAR_RIGHT")
                air_state_right = "off"
                logger.info(f"[CMD] -> C102/AIR = Desligar_RIGHT")
            continue
        else:            
            # se a temperatura externa for menor que a interna e a interna estiver baixa, desliga o ar
            if (last_temp_external is not None) and last_temp_external < last_temp and last_temp < MIN_TEMP_ON:
                logger.info(f"Temperatura externa ({last_temp_external}) menor que interna ({last_temp}). Desligando ar.")
                if air_state_left != "off":
                    send_air(client, f"DESLIGAR_LEFT")
                    air_state_left = "off"
                    logger.info(f"[CMD] -> C102/AIR = Desligar_LEFT")
                if air_state_right != "off":
                    send_air(client, f"DESLIGAR_RIGHT")
                    air_state_right = "off"
                    logger.info(f"[CMD] -> C102/AIR = Desligar_RIGHT")
                continue

            

        allShutdown = True;
        countOnPcs = 0
        for pc in computers_left.values():
            #print(pc.name, pc.is_stale())
            if not pc.is_stale():
                allShutdown = False
                logger.info(f"Continua ligado left {pc.name}")
                countOnPcs +=1
                break

        if allShutdown and air_state_left != "off":
            set_air_off_if_needed(client, "LEFT")
            logger.info("Desligar ar esquerdo por inatividade")        


        allShutdown = True;
        for pc in computers_right.values():
            #print(pc.name, pc.is_stale())
            if not pc.is_stale():
                allShutdown = False
                logger.info(f"Continua ligado right {pc.name}")
                break

        if allShutdown and air_state_right != "off":            
            set_air_off_if_needed(client, "RIGHT")
            logger.info("Desligar ar direito por inatividade")

        #if idle >= timedelta(minutes=IDLE_MINUTES):
            #set_air_off_if_needed(client)

# ========= PARSERS =========
def parse_temperature(payload) -> float | None:
    """
    Tenta extrair a TEMPERATURE do payload:
    - JSON com chave 'TEMPERATURE' (ou variações);
    - String numérica simples.
    """
    try:
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8", errors="ignore")

        # Se vier JSON
        if isinstance(payload, str) and payload.strip().startswith(("{", "[")):
            obj = json.loads(payload)
        else:
            obj = payload

        # JSON dict esperado
        if isinstance(obj, dict):
            # aceita várias formas de chave
            for k in ("TEMPERATURE", "temperature", "temp", "Temperature"):
                if k in obj:
                    v = obj[k]
                    try:
                        return float(v)
                    except:
                        return None
            # algumas integrações mandam lista de leituras
            if "sensors" in obj and isinstance(obj["sensors"], list):
                # procurar por sensor de temperatura
                for s in obj["sensors"]:
                    name = (s.get("name") or s.get("Name") or "").lower()
                    if "temp" in name or "am2302" in name or "dht" in name:
                        try:
                            return float(s.get("value") or s.get("Value"))
                        except:
                            pass
            return None

        # String numérica simples
        if isinstance(obj, str):
            try:
                return float(obj.strip().replace(",", "."))
            except:
                return None

        # Número já em float/int
        if isinstance(obj, (int, float)):
            return float(obj)

        return None
    except Exception:
        return None

# ========= CALLBACKS =========
def on_connect(client, userdata, flags, rc, properties=None):
    logger.info(f"Conectado ao broker, rc = {rc}")
    client.subscribe(TOPIC_PROC)
    client.subscribe(TOPIC_AM2302)
    client.subscribe(TOPIC_ENERGY)

def on_message(client, userdata, msg):
    global last_any_msg, last_temp, last_temp_ts, computers_left, computers_right, last_energy

    topic = msg.topic
    payload_raw = msg.payload
    
    #print(msg.payload)
    
    try:            
        payload = json.loads(payload_raw.decode("utf-8", errors="ignore"))
    except Exception:
        # se vier inválido, ainda assim conta como atividade
        payload = {}

    # Atualiza atividade (para qualquer mensagem de máquina em PROCESS_COMPUTERS)
    if topic == TOPIC_PROC:
        with lock:
            last_any_msg = datetime.now()

        computer = payload.get("ComputerName") or payload.get("Computer")
        logger.info(computer)
        
        if not computer:
            return       
        

        # Tenta ligar (condicionado à temperatura)]
        if computer in SIDE_LEFT:
            logger.info("Ligando ar esquerdo")
            computers_left[computer].updateDateTime()       
            set_air_on_if_needed(client, "LEFT")
        else:            
            set_air_on_if_needed(client, "RIGHT")
            computers_right[computer].updateDateTime()
            logger.info("Ligando ar direito")           

    elif topic == TOPIC_AM2302:
        temp = parse_temperature(payload_raw)
        located = payload.get("LOCATED")
        if temp is not None and located == "C102":
            with lock:
                last_temp = temp
                last_temp_ts = datetime.now()
                logger.info(f"Temperatura interna Atualizada: {last_temp}")
            # log leve
            # print(f"[TEMP] {last_temp:.1f}°C às {last_temp_ts}")
        elif temp is not None and located == "EXTERNO_CSTI":
            with lock:
                last_temp_external = temp
                logger.info(f"Temperatura Externa Atualizada: {last_temp_external}")
    elif topic == TOPIC_ENERGY:
        energy = payload.get("KWH")
        if energy is not None:
            with lock:
                last_energy = energy
                logger.info(f"Consumo de energia Atualizado: {last_energy} kwh")

# ========= MAIN =========
def main():
    client = mqtt.Client()

    client.tls_set(ca_certs=certificate_ca)
    # client.username_pw_set("usuario", "senha")

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)

    stop_event = threading.Event()
    t = threading.Thread(target=watchdog_thread, args=(client, stop_event), daemon=True)
    t.start()

    logger.info("Starting service...")

    try:
        with lock:
            # evita desligar imediato no boot
            global last_any_msg
            last_any_msg = datetime.now()
        client.loop_forever()
    finally:
        stop_event.set()
        t.join(timeout=2)

if __name__ == "__main__":
    main()
