🌐 **Português** | [English](./README.en.md)

# ServicosLinux — Smart Lab IoT & Digital Twin

Coleção de serviços, scripts e módulos para o gerenciamento inteligente de laboratórios computacionais (**Smart Lab / Smart Classroom**) do **Instituto Federal do Rio de Janeiro (IFRJ) — Campus Eng. Paulo de Frontin**.

O sistema integra sensores IoT (ESP), broker **MQTT (Mosquitto com TLS)**, banco de dados **PostgreSQL** e módulos de **Gêmeo Digital (Digital Twin)** com IA preditiva para monitorar e automatizar os laboratórios (ex.: C102 e C106): controle de ar-condicionado, monitoramento de energia, temperatura/umidade, status de portas e telemetria dos computadores.

> **Autor:** Rodrigo Mendes Peixoto

---

## 🏗️ Arquitetura Geral

```
[Sensores ESP / PCs Windows] --MQTT/TLS--> [Broker Mosquitto] --> [Serviços Python (listeners)]
                                                                        |
                                                                        v
                                                              [PostgreSQL (c102)]
                                                                        |
                                                                        v
                                                   [Engine Digital Twin + IA Preditiva]
```

---

## 📂 Estrutura do Repositório

### Serviços principais (Python)

| Arquivo | Descrição |
|---|---|
| `SmartLabServer.py` | Serviço central do Smart Lab. Controla o ar-condicionado com base na atividade dos computadores e na temperatura ambiente (tópicos `C102/PROCESS_COMPUTERS` e `C102/AM2302`). Liga o ar se houver computador ativo e temperatura alta; desliga após 5 min de inatividade. |
| `Producao/SmartLabServer.py` | Versão em produção do serviço SmartLabServer. |
| `CriandoBanco.py` | Listener MQTT seguro (TLS) que assina os tópicos de telemetria dos laboratórios, processa os payloads JSON e persiste os dados no PostgreSQL. |
| `MQTTBroker_InsertSQL_ENERGY_MONITOR.py` | Serviço que consome o tópico `C102/ENERGY_MONITOR` e insere as leituras de consumo de energia (kWh, pulsos) no banco. |
| `SensorExternoTemp.py` | Coleta de temperatura externa e gravação no PostgreSQL. |
| `SensorExternoTemp2.py` | Variação do sensor externo com servidor HTTP/HTTPS embutido (`ThreadingHTTPServer`). |

### Gêmeo Digital (Digital Twin)

| Arquivo | Descrição |
|---|---|
| `engineDigitalTwin.py` | Engine de execução de módulos: carrega dinamicamente os módulos definidos em `config.json`, gerencia threads, sinais e ciclo de vida (`setup`/`run`). |
| `ia_preditiva.py` | "Cérebro" do gêmeo digital — rede neural (PyTorch) + MPC (controle preditivo) com aprendizado contínuo. |
| `modules/dt_smartLaboratory.py` | Módulo SmartLab compatível com a engine (versão modularizada do SmartLabServer). |
| `modules/example_module.py` | Módulo de exemplo mostrando a interface esperada pela engine (`setup(context)` e `run(stop_event, context)`). |
| `config.json` | Configuração da engine — diretórios de módulos (`{BASE}/modules`, `{HOME}/smartlab/modules`). |

### Banco de dados

| Arquivo | Descrição |
|---|---|
| `SQL/Criação de tabelas.sql` | DDL das tabelas (ex.: `SENSOR_AM2302` para temperatura/umidade). |
| `Truncate tables postgres.txt` | Comandos utilitários para limpar tabelas no PostgreSQL. |

### Infraestrutura e configuração

| Arquivo | Descrição |
|---|---|
| `ConfiguraçãoIncialMosquitoo.txt` | Passo a passo da configuração inicial do Mosquitto: geração de certificados TLS (OpenSSL) e permissões. |
| `Comandos de ajuda.txt` | Comandos úteis do dia a dia: logs do Mosquitto, `journalctl` do serviço, criação de usuários do broker (`mosquitto_passwd`), exemplos de payload. |
| `ScriptFirewallMQTT.txt` | Script PowerShell para testar conectividade com o broker e criar regras de firewall (porta 8883). |
| `AddPortas.txt` | Comandos PowerShell para liberar a porta MQTT 8883 no firewall do Windows. |
| `Instalação Jupyter.sh` / `setup_jupyter.sh` | Scripts de instalação e configuração do Jupyter no servidor (criação do usuário `csti`, ambiente etc.). |
| `UpdateServiceWindows.ps1` | Atualizador do serviço Windows **SmartClassroom** a partir de um deploy central na rede (compara versões e atualiza automaticamente). |

### Exemplos e documentação auxiliar

| Arquivo/Pasta | Descrição |
|---|---|
| `jsonExamples/` | Exemplos de payloads JSON dos tópicos MQTT: `C102-AIR`, `C102-AM2302`, `C102-ENERGY_MONITOR`, `C102-DOOR_STATUS`, `C102-RELES`, `C102-STATUS`, `C102-IDLE`, `C102-LAST_STATUS`, `C102-SHUTDOWN_COMPUTER`, `C102_DISK_STATUS`, entre outros. |
| `PseudoCodigo.pseudo` / `Worker.pseudo` / `pseudo.xml` | Pseudocódigos e rascunhos de lógica do sistema. |


---

## 🚀 Como executar (visão geral)

1. **Broker MQTT (Mosquitto)**
   - Siga `ConfiguraçãoIncialMosquitoo.txt` para gerar certificados TLS.
   - Desabilite acesso anônimo e crie os usuários com `mosquitto_passwd` (ver `Comandos de ajuda.txt`).

2. **Banco de dados (PostgreSQL)**
   - Crie o banco (ex.: `c102`) e execute `SQL/Criação de tabelas.sql`.

3. **Serviços Python**
   ```bash
   pip install paho-mqtt psycopg2-binary torch
   python3 CriandoBanco.py            # listener de telemetria -> PostgreSQL
   python3 SmartLabServer.py          # automação do ar-condicionado
   python3 engineDigitalTwin.py       # engine do gêmeo digital (carrega modules/)
   ```

4. **Clientes Windows**
   - Libere a porta 8883 com `ScriptFirewallMQTT.txt` / `AddPortas.txt`.
   - Use `UpdateServiceWindows.ps1` para manter o serviço SmartClassroom atualizado.

5. **Monitoramento**
   ```bash
   sudo tail -f /var/log/mosquitto/mosquitto.log   # conexões no broker
   sudo journalctl -u smartlab.service -f          # logs do serviço
   ```

---

## 🧩 Tópicos MQTT monitorados (exemplos)

| Tópico | Conteúdo |
|---|---|
| `C102/AM2302` | Temperatura e umidade do laboratório |
| `C102/ENERGY_MONITOR` | Consumo de energia (kWh, pulsos, acumulado) |
| `C102/AIR` | Estado/controle do ar-condicionado |
| `C102/DOOR_STATUS` | Status da porta |
| `C102/PROCESS_COMPUTERS` | Atividade dos computadores |
| `C102/DISK_STATUS` | Status de disco das máquinas |

Payloads de exemplo estão em [`jsonExamples/`](./jsonExamples).

---

## 🛠️ Tecnologias

- **Python 3** — paho-mqtt, psycopg2, PyTorch
- **Mosquitto (MQTT)** com TLS
- **PostgreSQL**
- **PowerShell** (automação Windows)
- **Bash** (instalação/servidor Linux)

---

## 📄 Licença

Projeto acadêmico/institucional — IFRJ Campus Eng. Paulo de Frontin. Defina aqui a licença desejada (ex.: MIT, GPL-3.0).
