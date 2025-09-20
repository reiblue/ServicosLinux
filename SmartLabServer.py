import json
import threading
import time
from datetime import datetime, timedelta

import paho.mqtt.client as mqtt

# ========= CONFIG =========
BROKER_HOST = "10.11.102.123"
BROKER_PORT = 8883
KEEPALIVE   = 60

TOPIC_PROC  = r"C102\PROCESS_COMPUTERS"   # backslash mantido
TOPIC_AIR   = "C102/AIR"
TOPIC_AM2302 = "C102/AM2302"

SIDE_A = {
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
SIDE_B = {
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

IDLE_MINUTES = 1
MIN_TEMP_ON = 20.0   # condição para permitir Ligar_18

# ========= ESTADO =========
last_any_msg = datetime.min
air_state = "unknown"        # "on" | "off" | "unknown"
last_temp = None             # última TEMPERATURE recebida (float)
last_temp_ts = None

lock = threading.Lock()

# ========= AÇÕES =========
def send_air(client: mqtt.Client, command: str):
    client.publish(TOPIC_AIR, command, qos=0, retain=False)

def set_air_on_if_needed(client: mqtt.Client):
    """Liga somente se temperatura >= MIN_TEMP_ON."""
    global air_state, last_temp
    with lock:
        temp_ok = (last_temp is not None) and (last_temp >= MIN_TEMP_ON)
        if not temp_ok:
            # Sem temperatura válida ou abaixo do limite — não liga
            print(f"[INFO] Bloqueado Ligar_18: temperatura={last_temp} (min {MIN_TEMP_ON})")
            return
        if air_state != "on":
            send_air(client, "Ligar_18")
            air_state = "on"
            print("[CMD] -> C102/AIR = Ligar_18")

def set_air_off_if_needed(client: mqtt.Client):
    global air_state
    with lock:
        if air_state != "off":
            send_air(client, "Desligar")
            air_state = "off"
            print("[CMD] -> C102/AIR = Desligar")

# ========= WATCHDOG =========
def watchdog_thread(client: mqtt.Client, stop_event: threading.Event):
    global last_any_msg
    while not stop_event.is_set():
        time.sleep(30)
        with lock:
            idle = datetime.now() - last_any_msg
        if idle >= timedelta(minutes=IDLE_MINUTES):
            set_air_off_if_needed(client)

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
    print("Conectado ao broker, rc =", rc)
    client.subscribe(TOPIC_PROC)
    client.subscribe(TOPIC_AM2302)

def on_message(client, userdata, msg):
    global last_any_msg, last_temp, last_temp_ts

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
        print(computer)
        
        if not computer:
            return

        if computer in SIDE_A:
            # Tenta ligar (condicionado à temperatura)]
            
            set_air_on_if_needed(client)
        else:
            # Para lado B não há ação extra, mas resetamos o idle timer acima
            set_air_on_if_needed(client)
            

    elif topic == TOPIC_AM2302:
        temp = parse_temperature(payload_raw)
        located = payload.get("LOCATED")
        if temp is not None and located == "C102":
            with lock:
                last_temp = temp
                last_temp_ts = datetime.now()
                print("Temperatura Atualizada: ", last_temp)
            # log leve
            # print(f"[TEMP] {last_temp:.1f}°C às {last_temp_ts}")

# ========= MAIN =========
def main():
    client = mqtt.Client()
    client.tls_set(ca_certs="/home/csti/ca.crt")
    # client.username_pw_set("usuario", "senha")

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)

    stop_event = threading.Event()
    t = threading.Thread(target=watchdog_thread, args=(client, stop_event), daemon=True)
    t.start()

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
