# -*- coding: utf-8 -*-
# Módulo: ia_preditiva.py
# Descrição: Cérebro do Gêmeo Digital (Rede Neural + MPC + Aprendizado Contínuo)

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import logging

logger = logging.getLogger("ia_preditiva")

# ==============================================================================
# ARQUITETURA DA REDE NEURAL
# ==============================================================================
class RedeNeuralGimeoDigital(nn.Module):
    def __init__(self):
        super(RedeNeuralGimeoDigital, self).__init__()
        self.camada_oculta = nn.Linear(6, 32)
        self.camada_saida = nn.Linear(32, 3)

    def forward(self, E_k):
        x = F.relu(self.camada_oculta(E_k))
        return self.camada_saida(x)

# Variáveis globais do módulo de IA
modelo_ann = RedeNeuralGimeoDigital()
otimizador = optim.Adam(modelo_ann.parameters(), lr=0.01)
criterio_erro = nn.MSELoss()

# Memória curta para o aprendizado contínuo
memoria_ultimo_vetor = None  

# ==============================================================================
# FUNÇÕES EXPORTADAS
# ==============================================================================
def inicializar_ia(caminho_pesos='/home/csti/pesos_c102_c106.pth'):
    """Tenta carregar os pesos históricos. Se não achar, começa do zero."""
    try:
        modelo_ann.load_state_dict(torch.load(caminho_pesos))
        logger.info("[IA] Pesos históricos carregados com sucesso.")
    except Exception as e:
        logger.warning(f"[IA] Pesos não encontrados, iniciando IA virgem. Erro: {e}")

def avaliar_decisao_mpc(t_int, t_ext, h_int=50.0, h_ext=60.0):
    """
    Controlador MPC: Avalia as opções e retorna o comando ótimo.
    """
    global memoria_ultimo_vetor
    
    if t_int is None or t_ext is None:
        return None # Falha de segurança, devolve o controle para as regras fixas

    t_parede = t_int + 1.5 # Estimativa de massa térmica provisória
    T_c = 0.31 * t_ext + 17.8 # Norma ASHRAE 55
    
    peso_Q = 10.0
    peso_R = 5.0

    espaco_de_acoes = [
        {"comando": "DESLIGAR", "u_val": 0.0, "esforco": 0.0},
        {"comando": "LIGAR_26", "u_val": 1.0, "esforco": 0.4},
        {"comando": "LIGAR_24", "u_val": 2.0, "esforco": 0.7},
        {"comando": "LIGAR_23", "u_val": 3.0, "esforco": 1.0}
    ]

    menor_custo_J = float('inf')
    melhor_acao = None
    melhor_vetor = None

    modelo_ann.eval() # Modo de decisão (rápido)
    with torch.no_grad():
        for acao in espaco_de_acoes:
            E_k = torch.tensor([[t_int, h_int, t_parede, acao["u_val"], t_ext, h_ext]], dtype=torch.float32)
            y_futuro = modelo_ann(E_k)[0]
            
            desvio_termico = abs(y_futuro[0].item() - T_c)
            custo_J = (peso_Q * (max(0, desvio_termico - 2.5) ** 2)) + (peso_R * (acao["esforco"] ** 2))
            
            if custo_J < menor_custo_J:
                menor_custo_J = custo_J
                melhor_acao = acao["comando"]
                melhor_vetor = E_k

    # Salva o vetor escolhido na memória para podermos aprender com ele depois
    memoria_ultimo_vetor = melhor_vetor 
    return melhor_acao

def regenerar_conhecimento_ia(t_int_real, h_int_real=50.0):
    """
    Compara a previsão da última ação com a realidade do laboratório e ajusta o cérebro.
    """
    global memoria_ultimo_vetor
    
    if memoria_ultimo_vetor is None or t_int_real is None:
        return None # Não há nada para aprender ainda
        
    t_parede_real = t_int_real + 1.5
    
    modelo_ann.train() # Modo de aprendizado
    otimizador.zero_grad()
    
    previsao = modelo_ann(memoria_ultimo_vetor)
    realidade = torch.tensor([[t_int_real, h_int_real, t_parede_real]], dtype=torch.float32)
    
    erro = criterio_erro(previsao, realidade)
    erro.backward()
    otimizador.step()
    
    # Limpa a memória após aprender
    memoria_ultimo_vetor = None 
    return erro.item()