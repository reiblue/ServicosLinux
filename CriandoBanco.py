#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
=============================================================================
Projeto: Monitoramento IoT para Digital Twins e Smart Classrooms
Instituição: Instituto Federal do Rio de Janeiro (IFRJ) - Campus Eng. Paulo de Frontin
Autor: Rodrigo Mendes Peixoto
Data da Criação: 20/08/2025
Data de Atualização: 20 de Abril de 2026

Descrição:
    Este script atua como um serviço (listener) MQTT seguro via TLS, responsável
    por assinar, coletar e processar dados de telemetria dos computadores e 
    sensores dos laboratórios do campus (ex: C102 e C106). Os dados 
    extraídos dos payloads JSON são processados e persistidos de forma 
    relacional em um banco de dados PostgreSQL.

Principais Funcionalidades e Tópicos Monitorados:
    - Desempenho de Máquinas: Sensores de hardware, processos (CPU/PID), 
      armazenamento de disco e ociosidade (IDLE).
    - Controle de Sessão (KEEPALIVE/SHUTDOWN): Gestão de status de rede das 
      máquinas com inteligência de tempo (timeout de 45 minutos) para 
      identificação de quedas e religamentos.
    - Monitoramento Ambiental: Coleta de dados de temperatura e umidade 
      via sensores AM2302.
    - Eficiência Energética: Registro de consumo acumulado (KWh) e pulsos.
    - Automação e Acesso: Status de portas e comandos de relés.

Dependências e Infraestrutura:
    - paho-mqtt: Comunicação MQTT (Broker TLS na porta 8883)
    - psycopg2: Driver de conexão PostgreSQL (Database: 'c102')
    - Módulos nativos: json, datetime
=============================================================================
"""


import json
import psycopg2
import paho.mqtt.client as mqtt
from datetime import datetime

# ==== Configuração do PostgreSQL ====
db_config = {
    'dbname': 'c102',
    'user': 'csti',
    'password': '*1frj7csti7gov7br2024*',
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
    
def insert_door_status(cursor, located, status):
    cursor.execute("""
        INSERT INTO door_status (located, status)
        VALUES (%s, %s)
    """, (located, status))

def insert_reles_status(cursor, located, command, value):
    cursor.execute("""
        INSERT INTO device_command (located, command, value)
        VALUES (%s, %s, %s)
    """, (located, command, value))

def insert_disk_status(cursor, computer, total_size, free_space, used_space, used_percentage):
    cursor.execute("""
        INSERT INTO disk_status (computer, total_size, free_space, used_space, used_percentage)
        VALUES (%s, %s, %s, %s, %s)
    """, (computer, total_size, free_space, used_space, used_percentage))

def insert_idle(cursor, name, idle, total_runtime, effective_utilization):
    cursor.execute("""
        INSERT INTO idle_computer (name, idle, total_runtime, effective_utilization)
        VALUES (%s, %s, %s, %s)
    """, (name, idle, total_runtime, effective_utilization))

def process_machine_signal(cursor, machine_name, action_payload):
    # 1. Extração do local (Ex: CEPF-C102-C01 -> C102)
    partes = machine_name.split('-')
    location = partes[1] if len(partes) >= 2 else "DESCONHECIDO"

    # 2. Padroniza a ação recebida (keepalive vira RUNNING, resto vira SHUTDOWN)
    status_atual = 'RUNNING' if action_payload.lower() == 'keepalive' else 'SHUTDOWN'

    try:
        # 3. A consulta exata que você definiu: Filtra no banco pelos 45 minutos
        cursor.execute("""
            SELECT timestamp, action
            FROM KEEPALIVE 
            WHERE name = %s AND (NOW() - last_seen) <= INTERVAL '45 minutes'
            ORDER BY timestamp DESC 
            LIMIT 1
        """, (machine_name,))
        
        row = cursor.fetchone()

        # --- ÁRVORE DE DECISÃO ---

        if row:
            # O BANCO RETORNOU ALGO: O último sinal tem MENOS de 45 minutos.
            last_timestamp, last_action = row

            if status_atual == 'SHUTDOWN':
                # A máquina avisou que está desligando agora
                cursor.execute("""
                    UPDATE KEEPALIVE 
                    SET action = 'SHUTDOWN', last_seen = NOW() 
                    WHERE timestamp = %s AND name = %s
                """, (last_timestamp, machine_name))
                print(f"[{machine_name}] Desligamento explícito recebido e atualizado.")

            else: 
                # A máquina mandou 'keepalive' (status_atual == 'RUNNING')
                if last_action == 'RUNNING':
                    # Tudo normal, apenas atualiza o relógio da sessão atual
                    cursor.execute("""
                        UPDATE KEEPALIVE 
                        SET last_seen = NOW() 
                        WHERE timestamp = %s AND name = %s
                    """, (last_timestamp, machine_name))
                    print(f"[{machine_name}] Keepalive dentro do prazo. 'last_seen' atualizado.")
                
                elif last_action == 'SHUTDOWN':
                    # Máquina foi desligada oficialmente há pouco tempo, mas já ligou de novo
                    cursor.execute("""
                        INSERT INTO KEEPALIVE (name, location, action) 
                        VALUES (%s, %s, 'RUNNING')
                    """, (machine_name, location))
                    print(f"[{machine_name}] Religa rápida detectada. Nova sessão 'RUNNING' criada.")

        else:
            # O BANCO RETORNOU NONE: 
            # Duas possibilidades: Máquina ligada pela primeira vez OU passou de 45 minutos.
            # O Python simplesmente cria uma nova linha.
            cursor.execute("""
                INSERT INTO KEEPALIVE (name, location, action) 
                VALUES (%s, %s, %s)
            """, (machine_name, location, status_atual))
            
            motivo = "Primeira vez" if status_atual == 'SHUTDOWN' else "Gap > 45 min ou Primeira Vez"
            print(f"[{machine_name}] Nova linha inserida ({status_atual}). Motivo: {motivo}")

        # Confirma as alterações com segurança
        cursor.connection.commit()

    except Exception as e:
        cursor.connection.rollback()
        print(f"Erro ao processar {machine_name}: {e}")


# ==== Callback de conexão ====
def on_connect(client, userdata, flags, rc):
    print("Conectado com código: "+str(rc))
    client.subscribe("C102/HARDWARE_SENSORS")
    client.subscribe("C102/PROCESS_COMPUTERS")
    client.subscribe("C102/AM2302")
    client.subscribe("C102/ENERGY_MONITOR")
    client.subscribe("C102/DOOR_STATUS")
    client.subscribe("C102/RELES")
    client.subscribe("C102/DISK_STATUS")
    client.subscribe("C102/IDLE")

    print("Conectando com a sala C106")
    client.subscribe("C106/HARDWARE_SENSORS")
    client.subscribe("C106/PROCESS_COMPUTERS")
    client.subscribe("C106/AM2302")
    client.subscribe("C106/ENERGY_MONITOR")
    #client.subscribe("C106/DOOR_STATUS")
    #client.subscribe("C106/RELES")
    client.subscribe("C106/DISK_STATUS")
    client.subscribe("C106/IDLE")
    
    #client.subscribe("#")

# ==== Callback de mensagem ====
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()

        if msg.topic == "C102/HARDWARE_SENSORS" or msg.topic == "C106/HARDWARE_SENSORS":
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

        elif msg.topic == "C102/PROCESS_COMPUTERS" or msg.topic == "C106/PROCESS_COMPUTERS":
            computer_name = payload['ComputerName']
            #print("Time PROCESS_COMPUTERS: ", payload['Timestamp'])
            timestamp = payload['Timestamp']
            print('Process: ', computer_name, 'Time: ', timestamp)
            for process in payload['ProcessList']:
                insert_process(cursor, computer_name, process['PID'], process['CpuPercentage'], process['Name'], process['Timestamp'])
                #print(process['Name'], ' : ', process['Timestamp'])
        elif msg.topic == "C102/AM2302" or msg.topic == "C106/AM2302":
            print("payload:", payload['LOCATED'], "=", payload['TEMPERATURE'], "=",  payload['HUMIDITY'])
            insert_sensor_am2302(cursor, payload['LOCATED'], payload['TEMPERATURE'], payload['HUMIDITY'])
            print("Dados do sensor registrados")
        elif msg.topic == "C102/ENERGY_MONITOR":
            insert_kwh_consumption(cursor, payload['LOCATED'], payload['ACUMULADO'], payload['VALUE'], payload['PULSE'])
            print("Dados do sensor registrados")
#-----------------------------------------------------------------------------------------------------------------------------------------------------------

        elif msg.topic == "C102/DOOR_STATUS":
            insert_door_status(cursor, payload['LOCATED'], payload['STATUS'])
            print("Status da porta registrado")

        elif msg.topic == "C102/RELES":
            # JSON: {"LOCATED":"C102","COMMAND":"RELE","VALUE":false}
            insert_reles_status(cursor, payload['LOCATED'], payload['COMMAND'], payload['VALUE'])
            print("Status do relé registrado")

        elif msg.topic == "C102/DISK_STATUS" or msg.topic == "C106/DISK_STATUS":

            insert_disk_status(
                cursor,
                payload['COMPUTER'],
                payload['totalSize'],
                payload['freeSpace'],
                payload['usedSpace'],
                payload['usedPercentage']
            )
            print("Status do disco registrado")

        # Verifica se o tópico termina com /IDLE, não importa de qual laboratório venha
        # elif msg.topic.endswith("/IDLE"):
        elif msg.topic == "C102/IDLE" or msg.topic == "C106/IDLE":
            # Aqui depende do seu JSON real:
            # Se o payload usa JsonPropertyName: idle, ocioso, operacao, name
            insert_idle(
                cursor,
                payload['name'],
                payload['idle'],
                payload['ocioso'],
                payload['operacao']
            )
            print("Status de idle registrado")
        elif msg.topic == "C102/SHUTDOWN_COMPUTER" or msg.topic == "C106/SHUTDOWN_COMPUTER":
            # Print dinâmico para você saber exatamente o que chegou no log
            acao_recebida = payload['ACTION']
            maquina = payload['COMPUTER_NAME']
            print(f"Sinal de {acao_recebida} recebido da máquina {maquina}.")
            
            # Chama a nossa função inteligente que lida com os 45 minutos
            process_keepalive(
                cursor,
                maquina,
                acao_recebida               
            )

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
client.tls_insecure_set(True)
client.username_pw_set("python_user", "cst1!C3PF#2026@python")

client.on_connect = on_connect
client.on_message = on_message

client.connect("10.11.102.123", 8883, 60)  # Porta MQTT TLS


client.loop_forever()
