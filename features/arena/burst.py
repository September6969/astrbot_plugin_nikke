"""第一轮自动爆裂轴，按槽位决定同阶段启动顺序。"""

from .models import ArenaTeam, BurstChain, BurstStep, Provenance

MECHANICS = Provenance(
    "local-character-master; nikke-pvp-counter/build/template.html#chainOf",
    "60f8ac56b6c0660f702d74b89d36ade53ff6a8ca",
    "reference", ("cooldowns", "skill_levels", "treasures"),
)


def burst_chain(team: ArenaTeam) -> BurstChain:
    characters = team.characters
    has_b1 = any(char.burst == 1 for char in characters)
    stages = tuple(1 if char.adaptive_b1 and not has_b1 else char.burst for char in characters)
    used: set[int] = set()
    steps: list[BurstStep] = []
    missing: list[str] = []
    for stage in (1, 2, 3):
        # 全阶段角色的连续爆裂尚待样本确认，拒绝伪造完整轴。
        candidates = [i for i, value in enumerate(stages) if value == stage and i not in used]
        if not candidates:
            missing.append(f"B{stage}")
            break
        index = candidates[0]
        while True:
            char = characters[index]
            used.add(index)
            steps.append(BurstStep(stage, index + 1, char.key, char.name))
            reenter = char.reenter
            if char.conditional_reenter:
                reenter = any(value == 1 and not other.reenter and not other.conditional_reenter
                              for other, value in zip(characters, stages))
            if not reenter:
                break
            others = [i for i, value in enumerate(stages) if value == stage and i not in used]
            if not others:
                missing.append(f"再入B{stage}")
                break
            index = others[0]
        if missing:
            break
    return BurstChain(tuple(steps), not missing, tuple(missing), MECHANICS)
