import json
import tempfile
from pathlib import Path
from unittest import TestCase

from astrbot_plugin_nikke.idle_animation_resolver import IdleAnimationResolver


class IdleAnimationResolverTests(TestCase):
    def test_exact_idle_match_takes_precedence(self):
        animations = ["aim", "attack", "idle_mouth", "idle", "skill_01", "touch_body"]
        resolved = IdleAnimationResolver.resolve_from_animation_list(animations)
        self.assertEqual(resolved, "idle")

    def test_standby_token_precedence_when_idle_absent(self):
        # "standby" beats "standing", "wait", "stay"
        animations = ["stay_01", "standing_pose", "standby", "wait_loop"]
        resolved = IdleAnimationResolver.resolve_from_animation_list(animations)
        self.assertEqual(resolved, "standby")

        # "standing" beats "wait" and "stay"
        animations2 = ["stay_01", "standing", "wait_loop"]
        self.assertEqual(IdleAnimationResolver.resolve_from_animation_list(animations2), "standing")

        # prefix match idle_01 works
        animations3 = ["idle_02", "idle_01", "attack"]
        self.assertEqual(IdleAnimationResolver.resolve_from_animation_list(animations3), "idle_01")

    def test_strict_rejection_of_combat_and_action_tokens(self):
        combat_animations = [
            "aim_stand",
            "fire_burst",
            "shoot_loop",
            "attack_normal",
            "reload_start",
            "skill_cutin",
            "burst_start",
            "hit_light",
            "damage_heavy",
            "die_fall",
            "death_pose",
            "faint_loop",
            "walk_forward",
            "run_loop",
            "talk_01",
            "touch_head",
        ]
        resolved = IdleAnimationResolver.resolve_from_animation_list(combat_animations)
        self.assertIsNone(resolved, "All combat/action animations must be strictly rejected")

    def test_rejection_of_facial_overlay_tracks(self):
        facial_only = ["idle_mouth", "idle_mouthW", "mouth", "face_smile", "eye_blink"]
        resolved = IdleAnimationResolver.resolve_from_animation_list(facial_only)
        self.assertIsNone(resolved, "Facial overlay tracks must never be selected as body idle")

    def test_fail_closed_never_blindly_chooses_first_animation(self):
        bad_list = ["aim_pose", "attack_heavy", "reload_fast"]
        resolved = IdleAnimationResolver.resolve_from_animation_list(bad_list)
        self.assertIsNone(resolved)

        self.assertIsNone(IdleAnimationResolver.resolve_from_animation_list([]))
        self.assertIsNone(IdleAnimationResolver.resolve_from_animation_list(["", "   "]))

    def test_resolve_for_asset_verified_and_default(self):
        self.assertEqual(IdleAnimationResolver.resolve_for_asset("c010"), "idle")
        self.assertEqual(IdleAnimationResolver.resolve_for_asset("c010_02"), "idle")
        self.assertEqual(IdleAnimationResolver.resolve_for_asset("c010_03"), "idle")
        self.assertEqual(IdleAnimationResolver.resolve_for_asset("unknown_char"), "idle")

    def test_resolve_for_asset_with_provided_animations_enforces_validation(self):
        # If available animations are provided, resolver MUST validate against them
        valid_anims = ["aim", "idle", "reload"]
        self.assertEqual(IdleAnimationResolver.resolve_for_asset("c010", valid_anims), "idle")

        invalid_anims = ["aim", "reload", "die"]
        # Even though "c010" is verified, if the specific skeleton has no idle animation, fail closed!
        self.assertIsNone(IdleAnimationResolver.resolve_for_asset("c010", invalid_anims))

    def test_inspect_skeleton_animations_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            json_file = Path(temp_dir) / "test.json"
            json_file.write_text(
                json.dumps({"animations": {"idle": {}, "aim": {}, "idle_mouth": {}}}),
                encoding="utf-8",
            )
            anims = IdleAnimationResolver.inspect_skeleton_animations(json_file)
            self.assertEqual(sorted(anims), ["aim", "idle", "idle_mouth"])
            resolved = IdleAnimationResolver.resolve_from_animation_list(anims)
            self.assertEqual(resolved, "idle")
