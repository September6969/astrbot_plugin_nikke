"""复用插件受控别名与角色主表的竞技场身份解析。"""

import json
import re
import unicodedata
from dataclasses import replace
from pathlib import Path

from ..character.identity import CharacterDirectoryResolver
from .models import ArenaCharacter, ArenaTeam, Provenance


class ArenaDirectory:
    def __init__(self, master_path: Path, identity: CharacterDirectoryResolver):
        payload = json.loads(master_path.read_text(encoding="utf-8"))
        self.identity = identity
        self.rows = []
        self.characters = {}
        self.by_code = {}
        self._extra_names: dict[str, set[str]] = {}
        self._search_names: dict[str, list[str]] = {}
        provenance = Provenance("assets/data/character_master.json", "baseline-ede461f",
                                "reference", ("charge_parameters", "personal_configuration"))
        for raw in payload["characters"]:
            row = dict(raw, name_zh_cn=raw.get("name_cn", ""))
            key = row["character_key"]
            self.rows.append(row)
            self.characters[key] = ArenaCharacter(
                key, row["name_cn"] or row["name_zh_tw"], str(row["name_code"]),
                {"Step1": 1, "Step2": 2, "Step3": 3, "AllStep": 0}[row["burst"]],
                provenance, base_key=key,
                reenter=key in {"tia", "avistar", "alice_wonderland_bunny", "rupee_winter_shopper"},
                conditional_reenter=key == "anis_star", adaptive_b1=key == "rapi_red_hood",
                resource_id=str(row["resource_id"]),
            )
            code = str(row["name_code"])
            if code in self.by_code:
                raise ValueError("角色主表 name_code 存在歧义。")
            self.by_code[code] = key

    def resolve(self, text: str) -> ArenaCharacter:
        query = unicodedata.normalize("NFKC", text).strip()
        canonical = self.identity.resolve_canonical(query)
        if canonical in self.characters:
            return self.characters[canonical]
        exact = self._extra_names.get(query.casefold(), set())
        if len(exact) == 1:
            return self.characters[next(iter(exact))]
        matches = self.identity.find(self.rows, query)
        if len(matches) == 1:
            item = matches[0]
            # 子串只用于提示候选，执行要求完整标识或精确受控别名。
            values = [item.get(field, "") for field in
                      ("name_zh_cn", "name_zh_tw", "name_en", "name_code")]
            values.extend(item.get("aliases", []))
            if query.casefold() in {
                unicodedata.normalize("NFKC", str(value)).casefold() for value in values
            }:
                return self.characters[item["character_key"]]
        names = "、".join(self.characters[item["character_key"]].name for item in matches[:5])
        raise ValueError(f"角色“{query}”需要确认。" + (f"候选：{names}" if names else "请使用完整名称。"))

    def parse_team(self, text: str) -> ArenaTeam:
        if not isinstance(text, str) or len(text) > 1000:
            raise ValueError("阵容文本长度应在 1000 字以内。")
        normalized = unicodedata.normalize("NFKC", text).strip()
        parts = re.split(r"[/、,，\n]+", normalized)
        if len(parts) != 5 or any(not part.strip() for part in parts):
            raise ValueError("请按 P1–P5 输入五人，以 /、顿号或逗号分隔。")
        return ArenaTeam(tuple(self.resolve(part.strip()) for part in parts))

    def add_rules(self, rules: dict) -> None:
        for variant in rules["variants"]:
            base = self.characters[variant["base_key"]]
            char = replace(base, key=variant["key"], name=variant["name"],
                           burst=variant["burst"], base_key=base.key,
                           reenter=variant["key"] == "viper_treasure")
            self.characters[char.key] = char
        for key, translations in rules["names"].items():
            self._search_names[key] = list(translations.values())
            for name in translations.values():
                normalized = unicodedata.normalize("NFKC", name).strip().casefold()
                self._extra_names.setdefault(normalized, set()).add(key)

    def search_names(self, key: str) -> list[str]:
        names = list(self._search_names.get(key, ()))
        if key in self.characters:
            names.append(self.characters[key].name)
        for row in self.rows:
            if row["character_key"] == key:
                names.extend(self.identity.enrich(row).get("aliases", ()))
                break
        return list(dict.fromkeys(names))
