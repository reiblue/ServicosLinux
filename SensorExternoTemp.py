#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import psycopg2
from pathlib import Path

# ============ CONFIG ===============
db_user = "csti"
db_password = "*1frj7csti7gov7br"
db_host = "10.11.1.110" # Geralmente 'localhost' se o banco estiver na sua máquina
db_port = "5432"      # Porta padrão do PostgreSQL
db_name = "c102"

TABLE_NAME   = "sensor_am2302"
COL_LOCATED  = "located"
COL_TEMP     = "temperature"
COL_HUM      = "humidity"
COL_TS       = "timestamp"

REQUIRED_LOCATION = "EXTERNO_CSTI"
OUT_PATH = Path("/home/csti/externo_snippet.html")
# ====================================

FRAGMENT_TEMPLATE = (
    '<span id="temp">{temp:.1f}°C</span> | '
    '<span id="hum">{hum:.1f}%</span>'
)

def write_fragment(temp: float, hum: float) -> None:
    html = FRAGMENT_TEMPLATE.format(temp=temp, hum=hum)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"[HTML] {OUT_PATH} -> {html}")

def main():
    try:
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            dbname=db_name,
            user=db_user,
            password=db_password,
        )
        cursor = conn.cursor()

        query = f"""
            SELECT {COL_TEMP}, {COL_HUM}, {COL_TS}
            FROM {TABLE_NAME}
            WHERE {COL_LOCATED} = %s
            ORDER BY {COL_TS} DESC
            LIMIT 1
        """
        cursor.execute(query, (REQUIRED_LOCATION,))
        row = cursor.fetchone()

        if row:
            temp, hum, ts = row
            write_fragment(float(temp), float(hum))
        else:
            print(f"Nenhum registro para {REQUIRED_LOCATION}")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"[ERRO] {e}")

if __name__ == "__main__":
    main()
