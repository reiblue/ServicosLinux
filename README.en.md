🌐 [Português](./README.md) | **English**

# ServicosLinux — Smart Lab IoT & Digital Twin

A collection of services, scripts, and modules for the intelligent management of computer laboratories (**Smart Lab / Smart Classroom**) at the **Federal Institute of Rio de Janeiro (IFRJ) — Eng. Paulo de Frontin Campus**, Brazil.

The system integrates IoT sensors (ESP), an **MQTT broker (Mosquitto with TLS)**, a **PostgreSQL** database, and **Digital Twin** modules with predictive AI to monitor and automate the laboratories (e.g., C102 and C106): air-conditioning control, energy monitoring, temperature/humidity, door status, and computer telemetry.

> **Author:** Rodrigo Mendes Peixoto 

---

## 🏗️ General Architecture

```
[ESP Sensors / Windows PCs] --MQTT/TLS--> [Mosquitto Broker] --> [Python Services (listeners)]
                                                                        |
                                                                        v
                                                              [PostgreSQL (c102)]
                                                                        |
                                                                        v
                                                   [Digital Twin Engine + Predictive AI]
```

---

## 📂 Repository Structure

### Main services (Python)

| File | Description |
|---|---|
| `SmartLabServer.py` | Core Smart Lab service. Controls the air conditioning based on computer activity and room temperature (topics `C102/PROCESS_COMPUTERS` and `C102/AM2302`). Turns the AC on if a computer becomes active and the temperature is high; turns it off after 5 minutes of inactivity. |
| `Producao/SmartLabServer.py` | Production version of the SmartLabServer service. |
| `CriandoBanco.py` | Secure MQTT listener (TLS) that subscribes to the laboratories' telemetry topics, processes the JSON payloads, and persists the data into PostgreSQL. |
| `MQTTBroker_InsertSQL_ENERGY_MONITOR.py` | Service that consumes the `C102/ENERGY_MONITOR` topic and inserts energy consumption readings (kWh, pulses) into the database. |
| `SensorExternoTemp.py` | Collects outdoor temperature readings and stores them in PostgreSQL. |
| `SensorExternoTemp2.py` | Variant of the outdoor sensor service with an embedded HTTP/HTTPS server (`ThreadingHTTPServer`). |

### Digital Twin

| File | Description |
|---|---|
| `engineDigitalTwin.py` | Module execution engine: dynamically loads the modules defined in `config.json` and manages threads, signals, and lifecycle (`setup`/`run`). |
| `ia_preditiva.py` | The Digital Twin's "brain" — a neural network (PyTorch) + MPC (model predictive control) with continuous learning. |
| `modules/dt_smartLaboratory.py` | Engine-compatible SmartLab module (modularized version of SmartLabServer). |
| `modules/example_module.py` | Example module showing the interface expected by the engine (`setup(context)` and `run(stop_event, context)`). |
| `config.json` | Engine configuration — module directories (`{BASE}/modules`, `{HOME}/smartlab/modules`). |

### Database

| File | Description |
|---|---|
| `SQL/Criação de tabelas.sql` | Table DDL (e.g., `SENSOR_AM2302` for temperature/humidity). |
| `Truncate tables postgres.txt` | Utility commands for truncating tables in PostgreSQL. |

### Infrastructure and configuration

| File | Description |
|---|---|
| `ConfiguraçãoIncialMosquitoo.txt` | Step-by-step initial Mosquitto setup: TLS certificate generation (OpenSSL) and permissions. |
| `Comandos de ajuda.txt` | Useful day-to-day commands: Mosquitto logs, service `journalctl`, broker user creation (`mosquitto_passwd`), payload examples. |
| `ScriptFirewallMQTT.txt` | PowerShell script to test connectivity to the broker and create firewall rules (port 8883). |
| `AddPortas.txt` | PowerShell commands to open the MQTT port 8883 in the Windows firewall. |
| `Instalação Jupyter.sh` / `setup_jupyter.sh` | Scripts to install and configure Jupyter on the server (creation of the `csti` user, environment, etc.). |
| `UpdateServiceWindows.ps1` | Updater for the **SmartClassroom** Windows service from a central network deploy (compares versions and updates automatically). |

### Examples and auxiliary documentation

| File/Folder | Description |
|---|---|
| `jsonExamples/` | Example JSON payloads for the MQTT topics: `C102-AIR`, `C102-AM2302`, `C102-ENERGY_MONITOR`, `C102-DOOR_STATUS`, `C102-RELES`, `C102-STATUS`, `C102-IDLE`, `C102-LAST_STATUS`, `C102-SHUTDOWN_COMPUTER`, `C102_DISK_STATUS`, among others. |
| `PseudoCodigo.pseudo` / `Worker.pseudo` / `pseudo.xml` | Pseudocode and logic drafts of the system. |

---

## 🚀 How to run (overview)

1. **MQTT Broker (Mosquitto)**
   - Follow `ConfiguraçãoIncialMosquitoo.txt` to generate the TLS certificates.
   - Disable anonymous access and create the users with `mosquitto_passwd` (see `Comandos de ajuda.txt`).

2. **Database (PostgreSQL)**
   - Create the database (e.g., `c102`) and run `SQL/Criação de tabelas.sql`.

3. **Python services**
   ```bash
   pip install paho-mqtt psycopg2-binary torch
   python3 CriandoBanco.py            # telemetry listener -> PostgreSQL
   python3 SmartLabServer.py          # air-conditioning automation
   python3 engineDigitalTwin.py       # Digital Twin engine (loads modules/)
   ```

4. **Windows clients**
   - Open port 8883 using `ScriptFirewallMQTT.txt` / `AddPortas.txt`.
   - Use `UpdateServiceWindows.ps1` to keep the SmartClassroom service up to date.

5. **Monitoring**
   ```bash
   sudo tail -f /var/log/mosquitto/mosquitto.log   # broker connections
   sudo journalctl -u smartlab.service -f          # service logs
   ```

---

## 🧩 Monitored MQTT topics (examples)

| Topic | Content |
|---|---|
| `C102/AM2302` | Laboratory temperature and humidity |
| `C102/ENERGY_MONITOR` | Energy consumption (kWh, pulses, accumulated) |
| `C102/AIR` | Air-conditioning state/control |
| `C102/DOOR_STATUS` | Door status |
| `C102/PROCESS_COMPUTERS` | Computer activity |
| `C102/DISK_STATUS` | Machines' disk status |

Example payloads are available in [`jsonExamples/`](./jsonExamples).

---

## 🛠️ Technologies

- **Python 3** — paho-mqtt, psycopg2, PyTorch
- **Mosquitto (MQTT)** with TLS
- **PostgreSQL**
- **PowerShell** (Windows automation)
- **Bash** (Linux server setup)

---

## 📄 License

Academic/institutional project — IFRJ Eng. Paulo de Frontin Campus. Define the desired license here (e.g., MIT, GPL-3.0).
