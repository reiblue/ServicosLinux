from asyncio.log import logger
import os
import sys
import time
import signal
import traceback
import threading
import importlib.util
from dataclasses import dataclass, field
from typing import Dict, Optional, Any
import json
from pathlib import Path

# ===== CONFIG =====
BASE_DIR = Path(__file__).resolve().parent

def load_config():
    cfg_path = BASE_DIR / "config.json"
    if not cfg_path.exists():
        return {"modules_dirs": ["{BASE}/modules"]}
    return json.loads(cfg_path.read_text(encoding="utf-8"))

def resolve_placeholders(path_str: str) -> Path:
    # HOME cross-platform
    home = Path.home()

    path_str = (path_str
        .replace("{BASE}", str(BASE_DIR))
        .replace("{HOME}", str(home))
    )

    # Normaliza separadores e resolve relativo → absoluto
    p = Path(path_str)
    if not p.is_absolute():
        p = (BASE_DIR / p)
    return p.resolve()

config = load_config()
MODULES_DIRS = [resolve_placeholders(p) for p in config.get("modules_dirs", [])]
# ==================


@dataclass
class ModuleRuntime:
    name: str
    file_path: str
    thread: threading.Thread
    stop_event: threading.Event
    started_at: float = field(default_factory=time.time)
    error: Optional[str] = None


def load_module_from_file(module_name: str, file_path: str):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Não foi possível criar spec para {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def module_worker(module_name: str, file_path: str, stop_event: threading.Event, context: Dict[str, Any], runtime: ModuleRuntime):
    mod = None
    try:
        mod = load_module_from_file(module_name, file_path)

        # 1) SETUP (opcional)
        if hasattr(mod, "setup") and callable(mod.setup):
            mod.setup(context)

        # 2) RUN (obrigatório, com fallback)
        if hasattr(mod, "run") and callable(mod.run):
            mod.run(stop_event, context)
        elif hasattr(mod, "main") and callable(mod.main):
            mod.main()
        else:
            raise AttributeError(
                f"Módulo '{module_name}' não tem run(stop_event, context) nem main()."
            )

    except Exception:
        runtime.error = traceback.format_exc()
        logger.info(f"\n[ENGINE] ERRO no módulo '{module_name}':\n{runtime.error}\n")

    finally:
        # 3) TEARDOWN (opcional) — SEMPRE tenta rodar
        if mod is not None and hasattr(mod, "teardown") and callable(mod.teardown):
            try:
                mod.teardown(context)
            except Exception:
                tb = traceback.format_exc()
                logger.info(f"\n[ENGINE] ERRO no teardown do módulo '{module_name}':\n{tb}\n")


def list_all_py_files(dirs):
    files = []
    for d in dirs:
        if d.exists() and d.is_dir():
            for f in d.iterdir():
                if f.suffix == ".py" and not f.name.startswith("_"):
                    files.append(str(f))
    return sorted(files)


def make_module_name(file_path: str):
    base = os.path.splitext(os.path.basename(file_path))[0]
    return f"dyn_{base}"


def start_module(file_path: str, context: Dict[str, Any], runtimes: Dict[str, ModuleRuntime]) -> ModuleRuntime:
    module_name = make_module_name(file_path)

    stop_event = threading.Event()
    runtime = ModuleRuntime(name=module_name, file_path=file_path, thread=threading.Thread(), stop_event=stop_event)

    t = threading.Thread(
        target=module_worker,
        name=f"Thread-{module_name}",
        args=(module_name, file_path, stop_event, context, runtime),
        daemon=True
    )
    runtime.thread = t
    runtimes[module_name] = runtime
    t.start()

    logger.info(f"[ENGINE] Iniciado: {module_name} ({os.path.basename(file_path)})")
    return runtime


def stop_all(runtimes: Dict[str, ModuleRuntime], timeout: float = 10.0):
    logger.info("[ENGINE] Parando todos os módulos...")
    for rt in runtimes.values():
        rt.stop_event.set()

    deadline = time.time() + timeout
    for rt in runtimes.values():
        remaining = max(0.0, deadline - time.time())
        if rt.thread.is_alive():
            rt.thread.join(timeout=remaining)

    still_alive = [rt.name for rt in runtimes.values() if rt.thread.is_alive()]
    if still_alive:
        logger.info(f"[ENGINE] Atenção: ainda vivos após timeout: {still_alive}")
    else:
        logger.info("[ENGINE] Todos os módulos parados.")


def main():
    runtimes: Dict[str, ModuleRuntime] = {}

    # Contexto compartilhado: coloque aqui configs, broker mqtt, db, etc.
    context: Dict[str, Any] = {}

    shutdown_flag = threading.Event()

    def handle_signal(signum, frame):
        shutdown_flag.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    files = list_all_py_files(MODULES_DIRS)
    if not files:
        logger.info(f"[ENGINE] Nenhum módulo .py encontrado em: {MODULES_DIRS}")

    for fp in files:
        start_module(fp, context, runtimes)

    logger.info(f"[ENGINE] Carregou {len(files)} módulo(s). Rodando. (Ctrl+C para parar)")

    while not shutdown_flag.is_set():
        time.sleep(0.5)

    stop_all(runtimes)


if __name__ == "__main__":
    main()
