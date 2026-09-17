"""构图只消费经过图像绑定校验的离线锚点。"""
import hashlib
from unittest.mock import patch
from PIL import Image

from astrbot_plugin_nikke.features.character.face_anchor import framing
from astrbot_plugin_nikke.features.character.models import CostumeSelection
from astrbot_plugin_nikke.tests.test_character_replica import example_card


def test_anchor_binding_and_no_default_costume_fallback():
    card = example_card()
    card.resource_id, card.costume_id, card.costume_selection = "471", 0, CostumeSelection(0, "test", "default")
    image = Image.new("RGBA", (100, 200), "white")
    row = {"pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(), "point": [60, 40],
           "extent": [20, 10], "anchor_kind": "eye_attachment"}
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": row}):
        assert framing(card, image)["source"] == "eye_attachment"
        assert "left:-8.000px" in framing(card, image)["style"]
        assert framing(card, Image.new("RGBA", (100, 200), "black"))["source"] == "anchor_unavailable"
        card.costume_id = "unknown"
        card.costume_selection = CostumeSelection("unknown", "test", "unknown")
        assert framing(card, image)["source"] == "identity_unknown"


def test_missing_anchor_does_not_use_manual_character_offsets():
    card = example_card()
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={}):
        result = framing(card, Image.new("RGBA", (20, 30)))
        assert result["source"] == "anchor_unavailable"
        assert "object-fit:contain" in result["style"]


def test_resolution_variant_and_head_fallback():
    card = example_card()
    card.resource_id, card.costume_id = "471", 0
    card.costume_selection = CostumeSelection(0, "test", "default")
    image = Image.new("RGBA", (100, 200), "white")
    variant = {"pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(), "image_size": [100, 200],
               "point": [50, 50], "extent": None, "anchor_kind": "head_bone",
               "framing": {"target": [800, 600], "extent_width": 430}}
    with patch("astrbot_plugin_nikke.features.character.face_anchor.metadata", return_value={"c471": {"variants": [variant]}}):
        result = framing(card, image)
        assert result["source"] == "head_bone" and "left:200.000px" in result["style"]
        variant["image_size"] = [200, 100]
        assert framing(card, image)["source"] == "anchor_unavailable"
