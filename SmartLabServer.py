import json
import threading
import time
import logging
import sys
import paho.mqtt.client as mqtt
import sys
from datetime import datetime, timedelta, timezone
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
    certificate_ca = "C:\Program Files\SmartClassroom\ca.crt"
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
MIN_TEMP_ON = 20.0   # condição para permitir Ligar_18

# ========= ESTADO =========
last_any_msg = datetime.min
air_state_left = "unknown"        # "on" | "off" | "unknown"
air_state_right = "unknown"        # "on" | "off" | "unknown"
last_temp = 27             # última TEMPERATURE recebida (float)
last_temp_ts = None

lock = threading.Lock()

# ========= AÇÕES =========
def send_air(client: mqtt.Client, command: str):
    client.publish(TOPIC_AIR, command, qos=0, retain=False)

def set_air_on_if_needed(client: mqtt.Client, sideAir):
    """Liga somente se temperatura >= MIN_TEMP_ON."""
    global air_state_left, air_state_right, last_temp
    with lock:
        temp_ok = (last_temp is not None) and (last_temp >= MIN_TEMP_ON)
        if not temp_ok:
            # Sem temperatura válida ou abaixo do limite — não liga
            logger.info(f"[INFO] Bloqueado Ligar_18: temperatura={last_temp} (min {MIN_TEMP_ON})")
            return
        
        if sideAir == "LEFT" and air_state_left != "on":            
            send_air(client, f"LIGAR_18_{sideAir}")
            logger.info("Status air: ", air_state_left)
            air_state_left = "on"
            logger.info(f"[CMD] -> C102/AIR = LIGAR_18_{sideAir}")
        elif sideAir == "RIGHT" and air_state_right != "on":
            send_air(client, f"LIGAR_18_{sideAir}")
            logger.info("Status air: ", air_state_right)
            air_state_right = "on"
            logger.info(f"[CMD] -> C102/AIR = LIGAR_18_{sideAir}")

def set_air_off_if_needed(client: mqtt.Client, sideAir):
    global air_state_left, air_state_right
    with lock:
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
    global last_any_msg
    while not stop_event.is_set():
        time.sleep(30)
        with lock:
            idle = datetime.now() - last_any_msg
        
        allShutdown = True;
        for pc in computers_left.values():
            #print(pc.name, pc.is_stale())
            if not pc.is_stale():
                allShutdown = False
                logger.info("Continua ligado left ", pc.name)
                break

        if allShutdown:
            set_air_off_if_needed(client, "LEFT")        


        allShutdown = True;
        for pc in computers_right.values():
            #print(pc.name, pc.is_stale())
            if not pc.is_stale():
                allShutdown = False
                logger.info("Continua ligado right ", pc.name)
                break

        if allShutdown:            
            set_air_off_if_needed(client, "RIGHT")

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
def on_connect(client, userdata, flags, rc):
    logger.info("Conectado ao broker, rc =", rc)
    client.subscribe(TOPIC_PROC)
    client.subscribe(TOPIC_AM2302)

def on_message(client, userdata, msg):
    global last_any_msg, last_temp, last_temp_ts, computers_left, computers_right

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
                logger.info("Temperatura Atualizada: ", last_temp)
            # log leve
            # print(f"[TEMP] {last_temp:.1f}°C às {last_temp_ts}")

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
