"""消费经审核参数的静态 RL 充能估算器。"""

import math
from collections.abc import Mapping

from .models import ArenaTeam, Provenance, SpeedEstimate


def estimate_speed(
    team: ArenaTeam,
    parameters: Mapping[str, Mapping[float, float]],
    provenance: Provenance,
) -> SpeedEstimate:
    # 参数缺失时保持未知，避免用武器类型代替实际充能数值。
    if any(char.key not in parameters for char in team.characters):
        return SpeedEstimate(None, Provenance(provenance.source, provenance.version, "unknown",
                                             ("charge_parameters", "cubes", "overload", "skill_levels")))
    curves = [parameters[char.key] for char in team.characters]
    common = set(curves[0]).intersection(*(set(curve) for curve in curves[1:]))
    for tier in sorted(common):
        values = [curve[tier] for curve in curves]
        if not math.isfinite(tier) or tier <= 0 or any(
            not math.isfinite(value) or value < 0 for value in values
        ):
            raise ValueError("充能参数必须为有限非负数，RL 阶必须为正数。")
        if sum(values) >= 100:
            return SpeedEstimate(tier, provenance)
    return SpeedEstimate(None, Provenance(provenance.source, provenance.version, "unknown",
                                         ("charge_threshold_outside_snapshot",)))
