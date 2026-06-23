import os
import re
import sys
import yaml


def get_base_path():
    """
    Retorna a pasta base do sistema.

    No VSCode:
        D:/MES_Client_Complete

    No .exe:
        C:/Utility/MES
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)

    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_config_path():
    """
    O config.yaml deve ficar na raiz do projeto
    ou ao lado do .exe.
    """
    return os.path.join(get_base_path(), "config.yaml")


def _load_dotenv(base_path):
    """
    Carrega variáveis de um arquivo .env (se existir) para os.environ.
    Linhas no formato: CHAVE=valor  ou  # comentário
    Não sobrescreve variáveis já definidas no sistema.
    """
    env_path = os.path.join(base_path, ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


_ENV_VAR_PATTERN = re.compile(r"^\$\{(\w+)\}$")


def _resolve_env_vars(value):
    """
    Se o valor for exatamente ${NOME}, substitui pelo valor da variável de
    ambiente correspondente. Levanta erro se a variável não estiver definida.
    """
    if not isinstance(value, str):
        return value

    match = _ENV_VAR_PATTERN.match(value.strip())
    if not match:
        return value

    var_name = match.group(1)
    resolved = os.environ.get(var_name)
    if resolved is None:
        raise EnvironmentError(
            f"Variável de ambiente '{var_name}' não definida. "
            f"Defina-a no sistema ou no arquivo .env ao lado do executável."
        )
    return resolved


def _resolve_config(obj):
    """Percorre recursivamente o config resolvendo referências ${VAR}."""
    if isinstance(obj, dict):
        return {k: _resolve_config(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_config(item) for item in obj]
    return _resolve_env_vars(obj)


def load_config():
    """
    Carrega o arquivo config.yaml.
    Valores no formato ${NOME_VAR} são substituídos pela variável de ambiente
    correspondente (ou pelo arquivo .env ao lado do executável).
    """
    base_path = get_base_path()
    _load_dotenv(base_path)

    config_path = get_config_path()
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"config.yaml não encontrado em: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return _resolve_config(raw)


def load_raw_config():
    """
    Carrega o config.yaml SEM resolver referências ${VAR}.
    Use exclusivamente para salvar de volta no arquivo, preservando
    os placeholders de variáveis de ambiente (ex: ${MES_DB_PASSWORD}).
    """
    config_path = get_config_path()
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"config.yaml não encontrado em: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(config_data):
    """
    Salva alterações no config.yaml.
    Atenção: salva os valores como estão — referências ${VAR} são preservadas
    se você passar o config bruto (sem resolução).
    """
    config_path = get_config_path()

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f, allow_unicode=True, sort_keys=False)