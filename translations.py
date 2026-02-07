"""
Internationalization (i18n) support for qwen-bot.

Provides English and Chinese translations for all user-facing strings,
with per-user language preference storage and a helper function for lookups.
"""

import os

# Supported languages
LANGUAGES = {
    "en": "English",
    "zh": "中文",
}

# Global default language, configurable via DEFAULT_LANGUAGE env var (en or zh)
_env_lang = os.getenv("DEFAULT_LANGUAGE", "en").lower()
DEFAULT_LANGUAGE = _env_lang if _env_lang in LANGUAGES else "en"

# Per-user language preferences (user_id -> language code)
_user_languages: dict[int, str] = {}


def get_user_language(user_id: int) -> str:
    """Get the language preference for a user."""
    return _user_languages.get(user_id, DEFAULT_LANGUAGE)


def set_user_language(user_id: int, lang: str) -> None:
    """Set the language preference for a user."""
    _user_languages[user_id] = lang


def t(key: str, lang: str, **kwargs) -> str:
    """Get a translated string by key and language, with optional format arguments."""
    text = TRANSLATIONS.get(key, {}).get(lang)
    if text is None:
        # Fallback to English
        text = TRANSLATIONS.get(key, {}).get("en", key)
    if kwargs:
        text = text.format(**kwargs)
    return text


# All translatable strings
TRANSLATIONS = {
    # --- Natural language message responses ---
    "enqueued": {
        "en": "Got it, I have enqueued your request.",
        "zh": "收到，已将你的请求加入队列。",
    },
    "enqueued_multi": {
        "en": "Got it, I have enqueued your request with {img_count} image(s).",
        "zh": "收到，已将你的请求（含 {img_count} 张图片）加入队列。",
    },
    "gen_pipeline_unavailable": {
        "en": "Sorry, the generation pipeline is not available right now.",
        "zh": "抱歉，图片生成服务目前不可用。",
    },
    "edit_pipeline_unavailable": {
        "en": "Sorry, the edit pipeline is not available right now.",
        "zh": "抱歉，图片编辑服务目前不可用。",
    },
    "failed_submit_job": {
        "en": "Failed to submit job: {status}",
        "zh": "提交任务失败：{status}",
    },
    "invalid_request": {
        "en": "Invalid request: {detail}",
        "zh": "无效请求：{detail}",
    },
    "heres_your_image": {
        "en": "Here's your image!",
        "zh": "你的图片生成好了！",
    },
    "heres_your_edited_image": {
        "en": "Here's your edited image!",
        "zh": "你的编辑图片完成了！",
    },
    "something_went_wrong": {
        "en": "Sorry, something went wrong: {error}",
        "zh": "抱歉，出了点问题：{error}",
    },

    # --- Slash command responses ---
    "cmd_not_available": {
        "en": "This command is not available here.",
        "zh": "此命令在当前位置不可用。",
    },
    "gen_pipeline_not_available": {
        "en": "Generation pipeline is not available.",
        "zh": "图片生成服务不可用。",
    },
    "edit_pipeline_not_available": {
        "en": "Edit pipeline is not available.",
        "zh": "图片编辑服务不可用。",
    },
    "generating_image": {
        "en": "Generating image... (Job ID: `{job_id}`)",
        "zh": "正在生成图片……（任务ID：`{job_id}`）",
    },
    "editing_image": {
        "en": "Editing image... (Job ID: `{job_id}`)",
        "zh": "正在编辑图片……（任务ID：`{job_id}`）",
    },
    "attach_valid_image": {
        "en": "Please attach a valid image file.",
        "zh": "请附加一个有效的图片文件。",
    },
    "error": {
        "en": "Error: {error}",
        "zh": "错误：{error}",
    },

    # --- Embed titles ---
    "embed_generated_image": {
        "en": "Generated Image",
        "zh": "生成的图片",
    },
    "embed_edited_image": {
        "en": "Edited Image",
        "zh": "编辑后的图片",
    },
    "embed_job_status": {
        "en": "Job Status: {job_id}...",
        "zh": "任务状态：{job_id}...",
    },
    "embed_queue_status": {
        "en": "Queue Status",
        "zh": "队列状态",
    },
    "embed_system_info": {
        "en": "System Information",
        "zh": "系统信息",
    },

    # --- Embed field names ---
    "field_prompt": {
        "en": "Prompt",
        "zh": "提示词",
    },
    "field_negative_prompt": {
        "en": "Negative Prompt",
        "zh": "反向提示词",
    },
    "field_size": {
        "en": "Size",
        "zh": "尺寸",
    },
    "field_steps": {
        "en": "Steps",
        "zh": "步数",
    },
    "field_cfg": {
        "en": "CFG",
        "zh": "CFG",
    },
    "field_edit_instructions": {
        "en": "Edit Instructions",
        "zh": "编辑指令",
    },
    "field_type": {
        "en": "Type",
        "zh": "类型",
    },
    "field_status": {
        "en": "Status",
        "zh": "状态",
    },
    "field_progress": {
        "en": "Progress",
        "zh": "进度",
    },
    "field_error": {
        "en": "Error",
        "zh": "错误",
    },
    "field_queue_size": {
        "en": "Queue Size",
        "zh": "队列长度",
    },
    "field_total_jobs": {
        "en": "Total Jobs",
        "zh": "总任务数",
    },
    "field_completed": {
        "en": "Completed",
        "zh": "已完成",
    },
    "field_failed": {
        "en": "Failed",
        "zh": "失败",
    },
    "field_generation_jobs": {
        "en": "Generation Jobs",
        "zh": "生成任务",
    },
    "field_edit_jobs": {
        "en": "Edit Jobs",
        "zh": "编辑任务",
    },
    "field_current_job": {
        "en": "Current Job",
        "zh": "当前任务",
    },
    "field_device": {
        "en": "Device",
        "zh": "设备",
    },
    "field_cuda_available": {
        "en": "CUDA Available",
        "zh": "CUDA 可用",
    },
    "field_quantization": {
        "en": "Quantization",
        "zh": "量化",
    },
    "field_gpu": {
        "en": "GPU",
        "zh": "GPU",
    },
    "field_memory_allocated": {
        "en": "Memory Allocated",
        "zh": "已分配显存",
    },
    "field_memory_total": {
        "en": "Memory Total",
        "zh": "显存总量",
    },
    "field_gen_pipeline": {
        "en": "Generation Pipeline",
        "zh": "生成管线",
    },
    "field_edit_pipeline": {
        "en": "Edit Pipeline",
        "zh": "编辑管线",
    },
    "not_loaded": {
        "en": "not loaded",
        "zh": "未加载",
    },

    # --- /status command ---
    "job_not_found": {
        "en": "Job not found.",
        "zh": "未找到该任务。",
    },
    "failed_get_status": {
        "en": "Failed to get status: {status}",
        "zh": "获取状态失败：{status}",
    },
    "failed_get_queue": {
        "en": "Failed to get queue info: {status}",
        "zh": "获取队列信息失败：{status}",
    },
    "failed_get_system": {
        "en": "Failed to get system info: {status}",
        "zh": "获取系统信息失败：{status}",
    },

    # --- /language command ---
    "language_set": {
        "en": "Language set to **English**.",
        "zh": "语言已设置为**中文**。",
    },
    "language_current": {
        "en": "Current language: **{lang_name}**. Use `/language` to switch.",
        "zh": "当前语言：**{lang_name}**。使用 `/language` 切换。",
    },
}
