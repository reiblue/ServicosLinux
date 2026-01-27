import time

NAME_MODULE = "Example Module"

def setup(context):
    # parâmetros iniciais / inicialização
    context["modulo_exemplo_start"] = time.time()
    print(f"[{NAME_MODULE}] setup OK")

def run(stop_event, context):
    print(f"[{NAME_MODULE}] run loop")
    while not stop_event.is_set():
        # trabalho contínuo
        #print(f"[{NAME_MODULE}] trabalhando...")
        time.sleep(10)

def teardown(context):
    # finalização / limpeza
    started = context.get("modulo_exemplo_start")
    if started:
        print(f"[{NAME_MODULE}] teardown OK (rodou {time.time() - started:.1f}s)")
    else:
        print(f"[{NAME_MODULE}] teardown OK")