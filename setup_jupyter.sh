#!/bin/bash
set -e

echo "=============================="
echo "CRIANDO USUÁRIO csti"
echo "=============================="

# Criar usuário (se já existir, ignora)
if id "csti" &>/dev/null; then
    echo "Usuário csti já existe."
else
    adduser csti
	sudo usermod -aG sudo csti
	su csti
fi

sudo apt update && sudo apt upgrade -y
sudo apt install curl -y
cd /home/csti

wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh


conda create -n jupyter-env python=3.12 -y
conda activate jupyter-env


pip install jupyterlab
jupyter server --generate-config

echo "=============================="
echo "Defina uma senha para o jupyter"
echo "=============================="
jupyter server password

echo "=============================="
echo "CRIANDO ARQUIVO DE SERVIÇO"
echo "=============================="

sudo tee /etc/systemd/system/jupyter.service > /dev/null <<EOF
[Unit]
Description=Jupyter Lab
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=csti
WorkingDirectory=/home/csti
ExecStart=/home/csti/miniconda3/envs/jupyter-env/bin/jupyter lab \\
  --ip=0.0.0.0 \\
  --port=8888 \\
  --no-browser \\
  --ServerApp.allow_remote_access=True \\
  --ServerApp.allow_origin="*" \\
  --ServerApp.trust_xheaders=True

Restart=always

[Install]
WantedBy=multi-user.target
EOF

echo "=============================="
echo "HABILITANDO E INICIANDO SERVIÇO"
echo "=============================="

sudo systemctl daemon-reload
sudo systemctl enable jupyter.service
sudo systemctl start jupyter.service

echo "=============================="
echo "STATUS DO SERVIÇO"
echo "=============================="

sudo systemctl status jupyter.service --no-pager

echo "=============================="
echo "INSTALAÇÃO FINALIZADA!"
echo "ACESSE O JUPYTER VIA:"
echo "  http://SEU_IP_DO_SERVIDOR:8888"
echo "=============================="