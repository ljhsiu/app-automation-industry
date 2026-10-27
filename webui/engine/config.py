"""Web UI 配置加载

读取根目录 config.yaml 的 webui: 段，所有项均有内置默认值，
整段缺失也能正常启动 (设计文档 10.1 节)。

点击编排默认参数读取优先级:
    webui.sync_click_defaults > dual_click 段 > 代码内置默认值
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 仓库根目录: webui/engine/config.py -> 上溯 3 层
REPO_ROOT = Path(__file__).resolve().parents[2]

# 内置默认值 (config.yaml 整段缺失时使用)
DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8000,
    "auto_open_browser": True,
    "log_buffer_size": 5000,
    "log_dir": "./logs/webui",
    "metrics_push_interval": 0.5,
    "device_cache_ttl": 30,
    "stop_grace_break": 5,
    "stop_grace_term": 3,
    "sync_click_defaults": {
        "button_id": "com.keenon.solutionindustry:id/tv_start",
        "filter_texts": ["结束调度"],
        "poll_interval": 0.5,
        "click_cooldown": 2.0,
        "connect_retries": 3,
    },
}

_cache: dict | None = None


def repo_root() -> Path:
    return REPO_ROOT


def load_webui_config(refresh: bool = False) -> dict:
    """加载并缓存 webui 配置 (合并默认值)"""
    global _cache
    if _cache is not None and not refresh:
        return _cache

    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    cfg["sync_click_defaults"] = dict(DEFAULTS["sync_click_defaults"])

    config_path = REPO_ROOT / "config.yaml"
    data: dict = {}
    if config_path.exists():
        try:
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"config.yaml 加载失败，使用内置默认值: {e}")
            data = {}
    else:
        logger.warning(f"config.yaml 不存在: {config_path}，使用内置默认值")

    # webui: 段覆盖默认值
    webui = data.get("webui") or {}
    for key in DEFAULTS:
        if key in webui:
            if key == "sync_click_defaults" and isinstance(webui[key], dict):
                cfg["sync_click_defaults"].update(webui[key])
            else:
                cfg[key] = webui[key]

    # dual_click 段兜底 (老配置仍生效，不产生破坏性变更)
    dual_click = data.get("dual_click") or {}
    scd = cfg["sync_click_defaults"]
    if "button_id" not in (webui.get("sync_click_defaults") or {}):
        if dual_click.get("button_resourceId"):
            scd["button_id"] = dual_click["button_resourceId"]
    if "filter_texts" not in (webui.get("sync_click_defaults") or {}):
        if dual_click.get("filter_texts"):
            scd["filter_texts"] = list(dual_click["filter_texts"])

    # 相对路径锚定到仓库根目录
    log_dir = Path(cfg["log_dir"])
    cfg["log_dir"] = str(REPO_ROOT / log_dir if not log_dir.is_absolute() else log_dir)

    _cache = cfg
    return cfg
