# -*- coding: utf-8 -*-
# Requisitos: paho-mqtt já instalado (pip install paho-mqtt)
# autor: Rodrigo Mendes Peixoto
# email: rodrigo.peixoto@ifrj.edu.br
# data de criação: 2025-06-10
# data de modificação: 2025-12-08
# versão: 1.0.8
# descrição: Controla ar condicionado com base em atividade de computadores e temperatura ambiente.
# Observa mensagens MQTT em C102\PROCESS_COMPUTERS e C102/AM2302.
# Liga o ar se um computador ligar e a temperatura estiver alta.
# Desliga o ar se todos os computadores estiverem desligados por mais de 5 minutos

import json
import threading
import time
import logging
import sys
import paho.mqtt.client as mqtt
import sys
from typing import Final
from datetime import datetime, time as dtime, timedelta
from dataclasses import dataclass, field



VERSION: Final = "1.0.8"
SYSTEM_DESCRIPTION: Final = (
    "Gerenciamento de Laboratório Smart Lab\n"
    "Sistema Smart Lab para gerenciamento de laboratório computacional com 20 computadores, \n"
    "integrando sensores de temperatura e controle de ar-condicionado, monitoramento de energia elétrica, \n"
    "estado da porta e acionamento de relés, utilizando comunicação MQTT para automação \n"
    "e eficiência energética."
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)  # manda pro systemd
    ]
)

logger = logging.getLogger("SmartLabServer")

certificate_ca = ""

# ========= CONFIG =========
#BROKER_HOST = "10.11.4.111"
BROKER_HOST = "192.168.100.52"
BROKER_PORT = 8883
KEEPALIVE   = 60

TOPIC_COMPUTER_KEEPALIVE  = r"C102/SHUTDOWN_COMPUTER"   # backslash mantido
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
#TIME_SLEEP = 60 * 5
TIME_SLEEP = 60 
TIME_WAIT_COMPUTER_OFF = 20  # minutos
LABORATORY_SHUTDOWN = False
DOOR_STATUS = "NONE"  # "OPEN" | "CLOSED"



if sys.platform == "win32":        # Windows
    logger.info("rodando no Windows")
    #certificate_ca = r"C:\Program Files\SmartClassroom\ca.crt"
    certificate_ca = r"C:\Users\Peixoto\Documents\Pós-Graduações\Mestrado\UFJF - Computação\Pesquisa\certs\notebook.crt"
    #BROKER_HOST = "10.11.102.123"
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
        self.processes: Optional[bytes] = None
        self.sensors: Optional[bytes] = None
        self.lastActivity = datetime.now()
        self._last_ts = time.monotonic()  - timedelta(days=1).total_seconds() # começa "fresco"

    def touch(self):
        self.lastActivity = datetime.now()
        self._last_ts = time.monotonic()  # atualiza também aqui

    def updateDateTime(self):
        self.lastActivity = datetime.now()
        self._last_ts = time.monotonic()

    def is_stale(self, minutes: int = 1) -> bool:
        elapsed = time.monotonic() - self._last_ts
        # print(f"{self.name} parado há {elapsed:.1f}s")
        return elapsed >= minutes * 60
    
    def shutdownComputer(self):
        self._last_ts = time.monotonic() - timedelta(days=1).total_seconds()  # força stale

    def setProcesses(self, payload: bytes) -> None:
        self.processes = payload

    def setSensors(self, payload: bytes) -> None:
        self.sensors = payload


# ========= COMPUTADORES =========
SIDE_LEFT = {
    "CEPF-C102-C02",
    "CEPF-C102-C03",
    "CEPF-C102-C06",
    "CEPF-C102-C07",
    "CEPF-C102-C08",
    "CEPF-C102-C11",
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
    "CEPF-C102-C13",
    "CEPF-C102-C14",
    "CEPF-C102-C17",
    "CEPF-C102-C18",   
}

if sys.platform == "win32":
    SIDE_RIGHT.add("DESK-DELL-C01")
    SIDE_LEFT.add("CEPF-C102-V02")

computers_left: dict[str, Computador] = {}
computers_right: dict[str, Computador] = {}

for pc in SIDE_LEFT:
    computers_left[pc] = Computador(name=pc, side="LEFT")

for pc in SIDE_RIGHT:
    computers_right[pc] = Computador(name=pc, side="RIGHT")

IDLE_MINUTES = 7
MIN_TEMP_ON = 25.0   # condição para permitir Ligar_18
MIN_TEMP_OFF = 20.0
MIN_ENERGY =  0.1  # kwh, condição para permitir Ligar_18
# ========= ESTADO =========
last_any_msg = datetime.min
air_state_left = "off"        # "on" | "off" | "unknown"
air_state_right = "off"        # "on" | "off" | "unknown"
last_temp = 29             # última TEMPERATURE recebida (float)
last_temp_ts = None
last_temp_external = None
last_energy = 0.0         # última ENERGY recebida (float)
lock = threading.Lock()

# ========= AÇÕES =========
def send_air(client: mqtt.Client, command: str):
    client.publish(TOPIC_AIR, command + "\n", qos=0, retain=False)

def criar_json_shutdown(status: bool):
    data = {
        "SHUTDOWN": status
            }
    return json.dumps(data)

def sendMqttCommand(client: mqtt.Client, topic: str, command: bool):
    client.publish(topic, criar_json_shutdown(command) + "\n", qos=0, retain=False)

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
            send_air(client, f"LIGAR_23_{sideAir}")
            logger.info(f"Status air: {air_state_left}")
            #air_state_left = "on"
            logger.info(f"[CMD] -> C102/AIR = LIGAR_23_{sideAir}")
        elif sideAir == "RIGHT" and air_state_right != "on":
            send_air(client, f"LIGAR_23_{sideAir}")
            logger.info(f"Status air: {air_state_right}")
            #air_state_right = "on"
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
                #air_state_left = "off"
                logger.info(f"[CMD] -> C102/AIR = Desligar_LEFT")
            if air_state_right != "off":
                send_air(client, f"DESLIGAR_RIGHT")
                #air_state_right = "off"
                logger.info(f"[CMD] -> C102/AIR = Desligar_RIGHT")
            return

        #verifica a temperatura antes de desligar ambos os lados
        temp_ok = (last_temp is not None) and (MIN_TEMP_OFF <= last_temp)
        #desliga o ar se a temperatura for menor que MIN_TEMP_OFF
        if not temp_ok:
            send_air(client, f"DESLIGAR_LEFT")
            send_air(client, f"DESLIGAR_RIGHT")
            #air_state_left = "off"
            #air_state_right = "off"
            logger.info(f"[CMD] -> C102/AIR = Desligar ambos os lados por temperatura '{last_temp}' ou por atividade inicial")
            return
        
        if sideAir == "LEFT":
            if air_state_left != "off":
                send_air(client, f"DESLIGAR_{sideAir}")
                #air_state_left = "off"
                logger.info(f"[CMD] -> C102/AIR = Desligar_{sideAir}")
        else:
            if air_state_right != "off":
                send_air(client, f"DESLIGAR_{sideAir}")
                #air_state_right = "off"
                logger.info(f"[CMD] -> C102/AIR = Desligar_{sideAir}")
        

# ========= WATCHDOG =========
def watchdog_thread(client: mqtt.Client, stop_event: threading.Event):
    global last_any_msg, air_state_left, air_state_right, last_temp_external, last_temp, last_energy, MIN_ENERGY
    while not stop_event.is_set():
        time.sleep(TIME_SLEEP)
        with lock:
            idle = datetime.now() - last_any_msg

        allPCShutdownLeft = True;
        countOnPcs = 0
        for pc in computers_left.values():
            #print(pc.name, pc.is_stale())
            if not pc.is_stale(TIME_WAIT_COMPUTER_OFF):
                allPCShutdownLeft = False
                #logger.info(f"Continua ligado left {pc.name}")
                countOnPcs +=1
                #print(pc.name + " is on")
                break

        allPCShutdownRight = True;
        for pc in computers_right.values():
            #print(pc.name, pc.is_stale())
            if not pc.is_stale(TIME_WAIT_COMPUTER_OFF):
                allPCShutdownRight = False
                countOnPcs +=1
                #logger.info(f"Continua ligado right {pc.name}")
                #print(pc.name + " is on")
                break

        if allPCShutdownLeft and air_state_left != "off":
            set_air_off_if_needed(client, "LEFT")
            logger.info("Desligar ar esquerdo por inatividade")       
       

        if allPCShutdownRight and air_state_right != "off":            
            set_air_off_if_needed(client, "RIGHT")
            logger.info("Desligar ar direito por inatividade")

        if(not LABORATORY_SHUTDOWN  and allPCShutdownLeft and allPCShutdownRight):
            sendMqttCommand(client, "C102/STATUS", True)
            logger.info("Enviado comando de desligamento do laboratorio")
            

        if air_state_left == "off" and air_state_right == "off":
            if(last_energy > MIN_ENERGY and (allPCShutdownLeft and allPCShutdownRight)):
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
                #air_state_left = "off"
                logger.info(f"[CMD] -> C102/AIR = Desligar_LEFT")
            if air_state_right != "off":
                send_air(client, f"DESLIGAR_RIGHT")
                #air_state_right = "off"
                logger.info(f"[CMD] -> C102/AIR = Desligar_RIGHT")
            continue
        else:            
            # se a temperatura externa for menor que a interna e a interna estiver baixa, desliga o ar
            if (last_temp_external is not None) and last_temp_external < last_temp and last_temp < MIN_TEMP_ON:
                logger.info(f"Temperatura externa ({last_temp_external}) menor que interna ({last_temp}). Desligando ar.")
                if air_state_left != "off":
                    send_air(client, f"DESLIGAR_LEFT")
                    #air_state_left = "off"
                    logger.info(f"[CMD] -> C102/AIR = Desligar_LEFT")
                if air_state_right != "off":
                    send_air(client, f"DESLIGAR_RIGHT")
                    #air_state_right = "off"
                    logger.info(f"[CMD] -> C102/AIR = Desligar_RIGHT")
                continue
                  

        

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
    #Busca informações iniciais
    client.publish("C102/DOOR", "\n", qos=0, retain=False)
    sendMqttCommand(client, "C102/STATUS", True)

def on_message(client, userdata, msg):
    global last_any_msg, last_temp, last_temp_ts, last_temp_external, computers_left, computers_right, last_energy, air_state_left, air_state_right, DOOR_STATUS, LABORATORY_SHUTDOWN, TIME_WAIT_COMPUTER_OFF

    topic = msg.topic
    payload_raw = msg.payload
    
    #print(msg.payload)
    
    try:
        payload = json.loads(payload_raw.decode("utf-8"))       
        
    except Exception:
        payload = None
    
    if payload is None:
        return

    # Atualiza atividade (para qualquer mensagem de máquina em PROCESS_COMPUTERS)
    if topic == TOPIC_COMPUTER_KEEPALIVE:
        with lock:
            last_any_msg = datetime.now()

        computer = payload.get("COMPUTER_NAME") or payload.get("Computer")
        
        
        
        if not computer:
            return       
        

        action = payload.get("ACTION") 

        # Tenta ligar (condicionado à temperatura)]
        if computer in SIDE_LEFT:
            
            if action == "KEETALIVE":        
                #logger.info("Ligando ar esquerdo")
                computers_left[computer].updateDateTime()       
                set_air_on_if_needed(client, "LEFT")
                logger.info(computer + " receved message")
            elif action == "SHUTDOWN":
                computers_left[computer].shutdownComputer()
                logger.info(f"Computador {computer} desligado.")

        else:
            if action == "KEETALIVE":        
                #logger.info("Ligando ar esquerdo")
                computers_right[computer].updateDateTime()       
                set_air_on_if_needed(client, "RIGHT")
                logger.info(computer + " receved message")
            elif action == "SHUTDOWN":
                computers_right[computer].shutdownComputer()
                logger.info(f"Computador {computer} desligado.")  

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
    elif topic == TOPIC_STATUS_RELES:
        shutdown = payload.get("VALUE")

        LABORATORY_SHUTDOWN = not shutdown
        logger.info(f"Status de desligamento do laboratorio atualizado: {LABORATORY_SHUTDOWN}")
        
        
                
    elif topic == TOPIC_DOOR_OPEN:
        door_status = payload.get("STATUS")
        if door_status == "OPEN":
            LABORATORY_SHUTDOWN = False
            logger.info("Porta aberta. Reles acionados.")
            DOOR_STATUS = "OPEN"
        else:
            logger.info("Porta fechada.")
            DOOR_STATUS = "CLOSED"
    elif topic == TOPIC_RETURN_AIR:
        #print(payload)
        if payload is not None:            
            command = payload.get("COMMAND")
            if command is not None:
                air_state_left = str(payload.get("LEFT")).lower()
                air_state_right = str(payload.get("RIGHT")).lower()
                logger.info(f"Status do ar condicionado atualizado: LEFT={air_state_left}, RIGHT={air_state_right}")
    elif topic == TOPIC_STATUS_LABORATOY:  
        #envio de status do laboratorio para o último status do smartclassroom      
        payload = {
            "DOOR": DOOR_STATUS,
            "TEMPERATURE": last_temp,
            "TEMPERATURE_EXTERNAL": last_temp_external,
            "AIR_LEFT": air_state_left,
            "AIR_RIGHT": air_state_right,
            "ENERGY_KWH": last_energy,
            "LABORATORY_SHUTDOWN": LABORATORY_SHUTDOWN
        }
        json_payload = json.dumps(payload)
        client.publish("C102/LAST_STATUS", json_payload)
        
        for pc in computers_left.values():
            if not pc.is_stale(TIME_WAIT_COMPUTER_OFF):
                client.publish(TOPIC_PROCESS_COMPUTERS, pc.processes)
                client.publish(TOPIC_SENSORS, pc.sensors)
                

        for pc in computers_right.values():
            if not pc.is_stale(TIME_WAIT_COMPUTER_OFF):                
                client.publish(TOPIC_PROCESS_COMPUTERS, pc.processes)
                client.publish(TOPIC_SENSORS, pc.sensors)

        logger.info(f"Status do laboratorio solicitado. Enviando: {json_payload}")
    elif topic == TOPIC_PROCESS_COMPUTERS:

        
        
        computer = payload.get("ComputerName") or payload.get("Computer")
       

        if not computer:
            return              

        if computer in SIDE_LEFT:
            computers_left[computer].setProcesses(payload_raw)
        elif computer in SIDE_RIGHT:
            computers_right[computer].setProcesses(payload_raw)
         
    elif topic == TOPIC_SENSORS:

        try:
            # código que pode gerar erro
            computer = payload[0].get("COMPUTER_NAME") or payload[0].get("Computer")       

            if not computer:
                return              

            if computer in SIDE_LEFT:
                computers_left[computer].setSensors(payload_raw)
            elif computer in SIDE_RIGHT:
                computers_right[computer].setSensors(payload_raw)
        except Exception as e:
            logger.error(f"Erro ao processar sensores: {e}")

        
        

# ========= MAIN =========
def main():


    logger.info(SYSTEM_DESCRIPTION)

    logger.info(f"SmartLabServer v{VERSION} iniciando...")
    client = mqtt.Client()

    

    client.tls_set(ca_certs=certificate_ca)
    client.tls_insecure_set(True)
    client.username_pw_set("python_user", "cst1!C3PF#2026@python")

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
