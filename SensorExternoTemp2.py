#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Requisitos: psycopg2 já instalado (como no seu outro script)

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import psycopg2
import socket
import sys
import ssl

# ======== CONFIG BANCO =========
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
# ===============================

# ======== CONFIG SERVIDOR ======
BIND_ADDR = "0.0.0.0"   # ou "127.0.0.1" para local
PORT      = 3131
# ===============================

FRAGMENT_TEMPLATE = """<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Temperatura Umidade CEPF</title>
  <style>
    .rtecenter {{ text-align: center; }}
  </style>
</head>
<body>
  <p class="rtecenter">{temp:.1f}C | {hum:.1f}% </p>
</body>
</html>
"""



QUERY = f"""
    SELECT {COL_TEMP}, {COL_HUM}, {COL_TS}
    FROM {TABLE_NAME}
    WHERE {COL_LOCATED} = %s
    ORDER BY {COL_TS} DESC
    LIMIT 1
"""

def fetch_latest_fragment():
    """Consulta o último registro do sensor EXTERNO_CSTI e devolve o HTML fragmento."""
    conn = None
    try:
        conn = psycopg2.connect(
            host=db_host, port=db_port, dbname=db_name,
            user=db_user, password=db_password,
        )
        with conn.cursor() as cur:
            cur.execute(QUERY, (REQUIRED_LOCATION,))
            row = cur.fetchone()
            if not row:
                return None, "Nenhum registro encontrado"
            temp, hum, ts = row
            html = FRAGMENT_TEMPLATE.format(temp=float(temp), hum=float(hum))
            return html, None
    except Exception as e:
        return None, str(e)
    finally:
        if conn:
            conn.close()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # opcional: restrinja a rota, ex.: if self.path != "/externo": 404
        html, err = fetch_latest_fragment()
        if err:
            # 503 Service Unavailable para indicar falha na obtenção dos dados
            self.send_response(503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Erro ao obter dados: {err}\n".encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        # opcional: evitar cache
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    # silencia logs no stdout (opcional)
    def log_message(self, format, *args):
        return

def main():
    try:
        with ThreadingHTTPServer((BIND_ADDR, PORT), Handler) as httpd:
            host = BIND_ADDR if BIND_ADDR != "0.0.0.0" else socket.gethostname()
            print(f"Servidor ouvindo em http://{BIND_ADDR}:{PORT}  (host: {host})")
            httpd.serve_forever()
        
        """httpd = ThreadingHTTPServer((BIND_ADDR, PORT), Handler)

        # 🔹 Cria um contexto SSL moderno
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile="ssl.crt", keyfile="ssl.key")

        # 🔹 Envolve o socket do servidor
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

        host = BIND_ADDR if BIND_ADDR != "0.0.0.0" else socket.gethostname()
        print(f"Servidor ouvindo em https://{BIND_ADDR}:{PORT}  (host: {host})")
        httpd.serve_forever()"""
    except OSError as e:
        print(f"Falha ao iniciar servidor na porta {PORT}: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
