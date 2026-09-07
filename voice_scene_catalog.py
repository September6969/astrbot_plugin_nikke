"""从公开剧情详情交叉核对 speaker 与 voice_map，不猜测皮肤或互动用途。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SceneVoice:
    speech_id: str
    speaker: str
    voice_type: str = "story"
    skin: str | None = None


@dataclass(frozen=True)
class StoryVoiceMappingAudit:
    """单个剧情场景的映射审计，不把缺失字段提升为互动语音语义。"""

    scene_group_id: str
    map_count: int
    detail_count: int
    matched_ids: tuple[str, ...]
    map_only_ids: tuple[str, ...]
    detail_only_ids: tuple[str, ...]
    duplicate_map_ids: tuple[str, ...]
    speakers: tuple[str, ...]
    map_scope: str = "SCENE_GROUP_PREFIX"
    scope: str = "STORY_SCENE"
    interaction_type_evidence: str = "NOT_OBSERVED"
    skin_evidence: str = "NOT_OBSERVED"

    @property
    def coverage_complete(self) -> bool:
        """只有两侧 ID 集合完全相同，才称为该场景的完整交叉覆盖。"""
        return not self.map_only_ids and not self.detail_only_ids and not self.duplicate_map_ids


def _records(detail):
    if not isinstance(detail, dict):
        raise ValueError("剧情语音结构无效")
    try:
        rows = detail["scenario_group_id"]["records"]["value"]
    except (KeyError, TypeError):
        raise ValueError("剧情记录缺失") from None
    if not isinstance(rows, list):
        raise ValueError("剧情记录不是数组")
    return rows


def parse_scene_voices(detail, voice_map):
    if not isinstance(detail, dict) or not isinstance(voice_map, list) or not all(isinstance(item, str) for item in voice_map):
        raise ValueError("剧情语音结构无效")
    rows = _records(detail)
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


def audit_story_voice_mapping(scene_group_id, detail, voice_map) -> StoryVoiceMappingAudit:
    """审计一组公开 story 数据的 ID 覆盖，不推导角色、皮肤或互动类型。"""
    if not isinstance(scene_group_id, str) or not scene_group_id:
        raise ValueError("场景组 ID 无效")
    if not isinstance(voice_map, list) or not all(isinstance(item, str) for item in voice_map):
        raise ValueError("voice_map 结构无效")

    rows = _records(detail)
    # 当前公开 voice_map 按 scene_group_id 前缀汇总多个剧情场景；只审计
    # 当前场景前缀，不能把同一文件中的其它场景误算成缺失。
    map_ids = tuple(identifier for identifier in voice_map if identifier.startswith(scene_group_id + "_"))
    # 先复用严格 speaker 交叉校验，冲突数据不能被审计报告吞掉。
    parse_scene_voices(detail, list(map_ids))
    unique_map_ids = set(map_ids)
    detail_ids = []
    speakers = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("value")
        if not isinstance(value, dict):
            continue
        identifier = value.get("id")
        if isinstance(identifier, str):
            detail_ids.append(identifier)
        speaker = value.get("speaker")
        if isinstance(speaker, str) and speaker:
            speakers.add(speaker)

    detail_id_set = set(detail_ids)
    return StoryVoiceMappingAudit(
        scene_group_id=scene_group_id,
        map_count=len(unique_map_ids),
        detail_count=len(detail_id_set),
        matched_ids=tuple(sorted(unique_map_ids & detail_id_set)),
        map_only_ids=tuple(sorted(unique_map_ids - detail_id_set)),
        detail_only_ids=tuple(sorted(detail_id_set - unique_map_ids)),
        duplicate_map_ids=tuple(sorted(identifier for identifier in unique_map_ids if map_ids.count(identifier) > 1)),
        speakers=tuple(sorted(speakers)),
        map_scope="SCENE_GROUP_PREFIX",
        scope="STORY_SCENE",
        interaction_type_evidence="NOT_OBSERVED",
        skin_evidence="NOT_OBSERVED",
    )
