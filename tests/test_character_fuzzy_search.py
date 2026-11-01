from astrbot_plugin_nikke.features.character.identity import CharacterDirectoryResolver
from astrbot_plugin_nikke.features.character.application import CharacterAmbiguousMatch
from astrbot_plugin_nikke.application.commands.character import CharacterCommandHandler

def directory():
    return [
        {"name_code":"5185", "name_zh_tw":"瑪麗安：女王", "name_en":"Marian: Queen"},
        {"name_code":"5044", "name_zh_tw":"神罰", "name_en":"Modernia"},
        {"name_code":"581", "name_zh_tw":"阿爾卡娜", "name_en":"Arcana"},
    ]

def test_punctuation_case_and_spaces_are_ignored():
    r=CharacterDirectoryResolver()
    assert [x["name_code"] for x in r.find(directory(), "ＭＡＲＩＡＮ queen")] == ["5185"]
    assert [x["name_code"] for x in r.find(directory(), "瑪麗安 女王")] == ["5185"]

def test_typo_is_only_a_suggestion():
    r=CharacterDirectoryResolver()
    assert r.find(directory(), "Arcanna") == []
    assert [x["name_code"] for x in r.suggest(directory(), "Arcanna")] == ["581"]
    assert "5185" in [x["name_code"] for x in r.suggest(directory(), "玛丽安女王")]

def test_short_or_unknown_ids_are_not_guessed():
    r=CharacterDirectoryResolver()
    assert r.suggest(directory(), "玛丽") == []
    assert r.suggest(directory(), "5186") == []
    assert r.find(directory(), "5186") == []
    assert r.suggest(directory(), "完全不存在的人物") == []

def test_exact_match_and_candidate_identity_are_preserved():
    r=CharacterDirectoryResolver()
    rows=directory()+[{"name_code":"999", "name_en":"Arcana Extra"}]
    assert [x["name_code"] for x in r.find(rows,"Arcana")] == ["581"]
    assert [x["name_code"] for x in r.suggest(rows+rows,"Arcanna")].count("581") == 1

def test_single_suggestion_is_not_reported_as_multiple_matches():
    text=CharacterCommandHandler._ambiguous_message(CharacterAmbiguousMatch(("瑪麗安：女王",), suggestions_only=True))
    assert "没有精确匹配" in text
    assert "找到多个角色" not in text
