# -*- coding: utf-8 -*-

# Configuration Telegram
TELEGRAM_CONFIG = {
    "api_id": 21297856,
    "api_hash": "8a3d43dd2986184eb75aecc220b735d3",
    "bot_username": "@SmmKingdomTasksBot",
    "session_name": "tg_session"
}

# Configuration Instagram
INSTAGRAM_CONFIG = {
    "max_retries": 2,
    "request_delay": (3.0, 6.0),
    "action_delay": (5.0, 10.0), 
    "account_switch_delay": (30.0, 60.0),
    "max_tasks_per_account": 10,
    "skip_duration": 7200,  # 2 heures
    "existing_task_window": 120  # secondes
}

# Device configurations variées
DEVICE_CONFIGS = [
    {
        "app_version": "200.0.0.30.128",
        "android_version": 26,
        "android_release": "8.0.0",
        "dpi": "480dpi",
        "resolution": "1080x1920",
        "manufacturer": "samsung",
        "device": "SM-G935F",
        "model": "herolte",
        "cpu": "samsungexynos8890"
    },
    {
        "app_version": "200.0.0.30.128",
        "android_version": 29,
        "android_release": "10.0.0",
        "dpi": "420dpi",
        "resolution": "1080x2280",
        "manufacturer": "google",
        "device": "Pixel 4",
        "model": "pixel4",
        "cpu": "qualcomm"
    },
    {
        "app_version": "200.0.0.30.128",
        "android_version": 28,
        "android_release": "9.0.0",
        "dpi": "440dpi",
        "resolution": "1440x2880",
        "manufacturer": "samsung",
        "device": "SM-G960F",
        "model": "starlte",
        "cpu": "samsungexynos9810"
    },
    {
        "app_version": "200.0.0.30.128",
        "android_version": 27,
        "android_release": "8.1.0",
        "dpi": "400dpi",
        "resolution": "1080x2160",
        "manufacturer": "huawei",
        "device": "ANE-LX1",
        "model": "anne",
        "cpu": "hisilicon"
    }
]

# Fichiers de persistence
PERSISTENCE_FILES = {
    "last_account": "last_account.txt",
    "state": "state.json",
    "sessions": "session_{username}.json"
}

# Messages d'erreur à détecter
ERROR_PATTERNS = {
    "ip_blacklist": [
        "change your ip address",
        "blacklist", 
        "ip address",
        "black list"
    ],
    "challenge_required": [
        "challenge",
        "verify",
        "confirmation",
        "checkpoint",
        "phone",
        "sms"
    ],
    "wait_required": [
        "wait",
        "minutes", 
        "temporarily",
        "temporary",
        "try again later"
    ],
    "network_issues": [
        "problem with your request",
        "request",
        "connection", 
        "network"
    ]
}