import json
import psycopg2
import paho.mqtt.client as mqtt
from datetime import datetime

# ==== Configuração do PostgreSQL ====
db_config = {
    'dbname': 'c102',
    'user': 'root',
    'password': '',
    'host': 'localhost',
    'port': '5432'
}

# ==== Função para inserir no PostgreSQL ====
def insert_hardware_sensor(cursor, computer, name, sensor_type, sensor_name, value, timestamp):
    cursor.execute("""
        INSERT INTO hardware_sensors (computer, name, type, sensor_name, value, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (computer, name, sensor_type, sensor_name, value, timestamp))

def insert_process(cursor, computer_name, pid, cpu_percentage, name, timestamp):
    cursor.execute("""
        INSERT INTO process_computers (computer_name, pid, cpu_percentage, name, timestamp)
        VALUES (%s, %s, %s, %s, %s)
    """, (computer_name, pid, cpu_percentage, name, timestamp))

def insert_sensor_am2302(cursor, located, temperature, humidity):
    cursor.execute("""
        INSERT INTO SENSOR_AM2302 (located, temperature, humidity)
        VALUES (%s, %s, %s);
    """, (located, temperature, humidity))
    
def insert_kwh_consumption(cursor, location, accumulated, value, pulse):
    cursor.execute("""
        INSERT INTO KWH_CONSUMPTION (location, accumulated, value, pulse)
        VALUES (%s, %s, %s, %s)
    """, (location, accumulated, value, pulse))

# ==== Callback de conexão ====
def on_connect(client, userdata, flags, rc):
    print("Conectado com código: "+str(rc))
    client.subscribe("C102\\HARDWARE_SENSORS")
    client.subscribe("C102\\PROCESS_COMPUTERS")
    client.subscribe("C102/AM2302")
    client.subscribe("C102/ENERGY_MONITOR")
    #client.subscribe("#")

# ==== Callback de mensagem ====
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()

        if msg.topic == "C102\\HARDWARE_SENSORS":
            #print('Sensors', payload['Computer'], 'Time: ', payload['Timestamp'])
            for item in payload:
                computer = item['Computer']
                name = item['Name']
		#print('Hardware: ', computer, 'Time: ', timestamp)
                #print("Time HARDWARE_SENSORS: ", item['Timestamp'])
                timestamp = item['Timestamp']
                print('Sensors: ', computer, 'Time: ', timestamp)
                for sensor in item.get('Sensors', []):
                    insert_hardware_sensor(cursor, computer, name, sensor['Type'], sensor['Name'], sensor['Value'], timestamp)

        elif msg.topic == "C102\\PROCESS_COMPUTERS":
            computer_name = payload['ComputerName']
            #print("Time PROCESS_COMPUTERS: ", payload['Timestamp'])
            timestamp = payload['Timestamp']
            print('Process: ', computer_name, 'Time: ', timestamp)
            for process in payload['ProcessList']:
                insert_process(cursor, computer_name, process['PID'], process['CpuPercentage'], process['Name'], process['Timestamp'])
                #print(process['Name'], ' : ', process['Timestamp'])
        elif msg.topic == "C102/AM2302":
            print("payload:", payload['LOCATED'], "=", payload['TEMPERATURE'], "=",  payload['HUMIDITY'])
            insert_sensor_am2302(cursor, payload['LOCATED'], payload['TEMPERATURE'], payload['HUMIDITY'])
            print("Dados do sensor registrados")
        elif msg.topic == "C102/ENERGY_MONITOR":
            insert_kwh_consumption(cursor, payload['LOCATED'], payload['ACUMULADO'], payload['VALUE'], payload['PULSE'])
            print("Dados do sensor registrados")

        print(msg.topic)

        conn.commit()
        cursor.close()
        conn.close()
        print(f"Dados inseridos do tópico {msg.topic}")

    except Exception as e:
        print(f"Erro ao processar mensagem: {e}")

# ==== Configuração do MQTT ====
client = mqtt.Client()
client.tls_set(ca_certs="/home/csti/ca.crt")  # Se estiver usando TLS
#client.username_pw_set("usuario", "senha")  # Se necessário
client.on_connect = on_connect
client.on_message = on_message

client.connect("10.11.102.123", 8883, 60)  # Porta MQTT TLS


client.loop_forever()
