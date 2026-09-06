"""从公开剧情详情交叉核对 speaker 与 voice_map，不猜测皮肤或互动用途。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SceneVoice:
    speech_id: str
    speaker: str
    voice_type: str = "story"
    skin: str | None = None


def parse_scene_voices(detail, voice_map):
    if not isinstance(detail, dict) or not isinstance(voice_map, list) or not all(isinstance(item, str) for item in voice_map):
        raise ValueError("剧情语音结构无效")
    try:
        rows = detail["scenario_group_id"]["records"]["value"]
    except (KeyError, TypeError):
        raise ValueError("剧情记录缺失") from None
    if not isinstance(rows, list):
        raise ValueError("剧情记录不是数组")
    allowed = set(voice_map)
    voices = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("value")
        speaker = row.get("speaker")
        if not isinstance(value, dict) or not isinstance(speaker, dict):
            continue
        identifier, who = value.get("id"), value.get("speaker")
        if not isinstance(identifier, str) or identifier not in allowed:
            continue
        if not isinstance(who, str) or not who or speaker.get("value") != who:
            raise ValueError("语音 speaker 映射冲突")
        item = SceneVoice(identifier, who)
        if identifier in voices and voices[identifier] != item:
            raise ValueError("同一语音 ID 映射到不同角色")
        voices[identifier] = item
    return list(voices.values())
