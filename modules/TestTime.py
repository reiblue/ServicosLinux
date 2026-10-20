# -*- coding: utf-8 -*-
import time
import threading
import os
import sys
import statistics
from datetime import datetime
import paho.mqtt.client as mqtt

# ================= CONFIGURAÇÕES =================
BROKER_HOST = "10.11.4.111"
BROKER_PORT = 8883
DIRETORIO_LOGS = "/home/csti/modules/teste/resultados"

# Define o caminho do certificado dinamicamente
if sys.platform == "win32":
    CA_CERT = r"C:\Program Files\SmartClassroom\ca.crt"
else:
    CA_CERT = "/home/csti/ca.crt"

TOPIC_CMD = "C106/AR_CONDICIONADO"
TOPIC_RESP = "C106/AIR"

evento_resposta = threading.Event()
tempo_recebimento = 0.0

# ================= CALLBACKS =================
def on_connect(client, userdata, flags, rc):
    """Inscreve no tópico de resposta assim que conectar."""
    if rc == 0:
        client.subscribe(TOPIC_RESP)
    else:
        print(f"Falha na conexão. Código: {rc}")

def on_message(client, userdata, msg):
    """Registra o tempo exato em que a resposta do sensor chegou."""
    global tempo_recebimento
    if msg.topic == TOPIC_RESP:
        # Usa perf_counter para medição de altíssima precisão
        tempo_recebimento = time.perf_counter()
        evento_resposta.set()

# ================= MÉTODO PRINCIPAL =================
def medir_tempo_resposta(n_testes=10, timeout=10.0):
    client = mqtt.Client()
    
    # Verificação do certificado antes de tentar conectar
    if os.path.exists(CA_CERT):
        client.tls_set(ca_certs=CA_CERT)
        client.tls_insecure_set(True)
        client.username_pw_set("python_user", "cst1!C3PF#2026@python")
    else:
        print(f"ERRO: Certificado não encontrado no caminho: {CA_CERT}")
        return
    
    client.on_connect = on_connect
    client.on_message = on_message
    
    print(f"Conectando ao broker {BROKER_HOST}...")
    client.connect(BROKER_HOST, BROKER_PORT, 60)
    client.loop_start()
    
    time.sleep(10) # Aguarda inscrição no tópico
    
    tempos_resposta_ms = []
    
    # Captura e formata o horário de início
    horario_inicio = datetime.now()
    str_inicio = horario_inicio.strftime("%d/%m/%Y %H:%M:%S")
    print(f"\nIniciando bateria de {n_testes} testes em: {str_inicio}\n")

    # Cria o nome do arquivo no formato teste_DIA-MES-ANO_HORA-MINUTO.txt
    nome_arquivo = f"teste_{horario_inicio.strftime('%d-%m-%Y_%H-%M')}.txt"
    
    # Cria o caminho completo (junta a pasta com o arquivo)
    caminho_completo = os.path.join(DIRETORIO_LOGS, nome_arquivo)
    
    # Garante que a pasta exista (cria se não existir)
    os.makedirs(DIRETORIO_LOGS, exist_ok=True)
    
    for i in range(n_testes):
        evento_resposta.clear()
        
        # Início da medição
        tempo_envio = time.perf_counter()
        client.publish(TOPIC_CMD, payload='{"comando": "ping"}', qos=1)
        
        recebeu_resposta = evento_resposta.wait(timeout=timeout)
        
        if recebeu_resposta:
            # (Tempo final - Tempo inicial) * 1000 = Milissegundos
            rtt_ms = (tempo_recebimento - tempo_envio) * 1000
            tempos_resposta_ms.append(rtt_ms)
            print(f"Teste {i+1}/{n_testes}: {rtt_ms:.2f} ms")
        else:
            print(f"Teste {i+1}/{n_testes}: Timeout (sem resposta em {timeout}s)")
            
        time.sleep(10) # Pausa de 10s ajustada para ser confortável para o equipamento
        
    # Captura o horário de término e calcula a duração total
    horario_fim = datetime.now()
    str_fim = horario_fim.strftime("%d/%m/%Y %H:%M:%S")


    
    duracao_total = horario_fim - horario_inicio
    # Removemos os microsegundos da string para ficar visualmente mais limpo
    duracao_formatada = str(duracao_total).split('.')[0]
    
    client.loop_stop()
    client.disconnect()
    
    # Resultados
    if tempos_resposta_ms:
        media_ms = sum(tempos_resposta_ms) / len(tempos_resposta_ms)
        menor_ms = min(tempos_resposta_ms)
        maior_ms = max(tempos_resposta_ms)
        
        # Estatísticas avançadas precisam de mais de uma amostra
        if len(tempos_resposta_ms) > 1:
            desvio_padrao_ms = statistics.stdev(tempos_resposta_ms)
            try:
                quartis = statistics.quantiles(tempos_resposta_ms, n=4)
                iqr_ms = quartis[2] - quartis[0] # Q3 - Q1
            except ValueError:
                iqr_ms = 0.0
        else:
            desvio_padrao_ms = 0.0
            iqr_ms = 0.0
        
        # Monta o texto do resumo completo
        resumo = (
            f"\n" + "-" * 40 + "\n"
            f"RESUMO DOS RESULTADOS\n"
            f"-" * 40 + "\n"
            f"Início da execução:      {str_inicio}\n"
            f"Término da execução:     {str_fim}\n"
            f"Duração total do teste:  {duracao_formatada}\n"
            f"-" * 40 + "\n"
            f"Menor tempo de resposta: {menor_ms:.2f} ms\n"
            f"Maior tempo de resposta: {maior_ms:.2f} ms\n"
            f"Média de resposta:       {media_ms:.2f} ms\n"
            f"Desvio Padrão:           {desvio_padrao_ms:.2f} ms\n"
            f"Intervalo Interquartil:  {iqr_ms:.2f} ms\n"
            f"Sucesso:                 {len(tempos_resposta_ms)}/{n_testes} pacotes\n"
            f"-" * 40 + "\n"
        )
        
        # Imprime na tela
        print(resumo)
        
        # Salva no arquivo de texto usando o caminho completo
        with open(caminho_completo, "w", encoding="utf-8") as arquivo:
            arquivo.write(resumo)
            
        print(f"Os resultados foram salvos com sucesso no arquivo: {caminho_completo}")
            
    else:
        print(f"\nTérmino: {str_fim}")
        print(f"Duração total do teste: {duracao_formatada}")
        print("Nenhuma resposta recebida do sensor durante os testes.")

if __name__ == "__main__":
    quantidade_testes = 10  # Valor padrão
    
    # Verifica se algum argumento foi passado na chamada do script
    if len(sys.argv) > 1:
        try:
            quantidade_testes = int(sys.argv[1])
        except ValueError:
            print(f"Aviso: '{sys.argv[1]}' não é um número válido. Usando o padrão de 10 testes.")
            quantidade_testes = 10
            
    medir_tempo_resposta(n_testes=quantidade_testes)