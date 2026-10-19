"""目录迁移后的离线资源、工作目录和命令兼容回归。"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

from astrbot_plugin_nikke.core.paths import PLUGIN_ROOT, builtin_dir, builtin_file, builtin_roots, manifest_candidates
from astrbot_plugin_nikke.core.assets.image_cache import AssetImageCache
from astrbot_plugin_nikke.core.asset_manager import AssetManager
from astrbot_plugin_nikke.features.character.lineup_portrait_resolver import LineupPortraitResolver
from astrbot_plugin_nikke.features.raid.boss_resolver import BossAssetResolver


def test_resource_precedence_and_readonly_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assets = tmp_path / 'plugin/assets'
    old = assets.parent / 'fonts'
    new = assets / 'fonts'
    old.mkdir(parents=True)
    (old / 'font.otf').write_bytes(b'old')
    assert builtin_file('fonts', 'font.otf', asset_dir=assets) == old / 'font.otf'
    new.mkdir(parents=True)
    (new / 'font.otf').write_bytes(b'new')
    assert builtin_file('fonts', 'font.otf', asset_dir=assets).read_bytes() == b'new'
    assert (old / 'font.otf').read_bytes() == b'old'
    assert builtin_dir('blablalink') == PLUGIN_ROOT / 'assets/blablalink'


def test_offline_resolvers_ignore_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    portraits = LineupPortraitResolver()
    bosses = BossAssetResolver()
    assert portraits._tid_to_char and portraits._avatar_map
    assert bosses.manifest_records
    assert portraits.fallback_file.is_file()
    assert bosses.fallback_file.is_file()
    manager = AssetManager(tmp_path / 'cache', PLUGIN_ROOT / 'assets', remote=False)
    try:
        assert manager.blabla_assets_dir == PLUGIN_ROOT / 'assets/blablalink'
        new = manager.image_cache.load('assets/blablalink/character/si/default_avatar.webp')
        old = manager.image_cache.load('data/nikke/blabla-assets/character/si/default_avatar.webp')
        assert isinstance(new, Image.Image) and isinstance(old, Image.Image)
        assert new.tobytes() == old.tobytes()
    finally:
        manager.close()


def test_partial_migration_keeps_per_file_fallback(tmp_path):
    assets = tmp_path / 'plugin/assets'
    new, old = builtin_roots('blablalink', asset_dir=assets)
    new.mkdir(parents=True)
    (old / 'character/si').mkdir(parents=True)
    Image.new('RGB', (8, 8), 'red').save(old / 'character/si/test.png')
    cache = AssetImageCache(tmp_path / 'cache', assets, extra_roots=(new, old))
    image = cache.load('assets/blablalink/character/si/test.png')
    assert image is not None and image.size == (8, 8)
    new_manifest, old_manifest = builtin_roots('manifests/blablalink', asset_dir=assets)
    new_manifest.mkdir(parents=True)
    old_manifest.mkdir(parents=True)
    (new_manifest / 'test.json').write_text('new', encoding='utf-8')
    (old_manifest / 'test.json').write_text('old', encoding='utf-8')
    assert manifest_candidates('test.json', assets, old)[0] == new_manifest / 'test.json'


def test_compat_entry_preserves_parameters_exit_and_keyboard_interrupt(tmp_path):
    scripts = tmp_path / 'scripts'
    (scripts / 'shared').mkdir(parents=True)
    (scripts / 'spine').mkdir()
    (scripts / 'shared/compat.py').write_bytes((PLUGIN_ROOT / 'scripts/shared/compat.py').read_bytes())
    shim = (PLUGIN_ROOT / 'scripts/spine_batch_validation.py').read_text(encoding='utf-8')
    (scripts / 'cancel_probe.py').write_text(shim.replace('spine.spine_batch_validation', 'spine.cancel_probe'), encoding='utf-8')
    target = scripts / 'spine/cancel_probe.py'
    target.write_text('import signal, sys\ntry:\n    print(repr(sys.argv[1:]), flush=True)\n    if "cancel" in sys.argv: signal.raise_signal(signal.SIGINT)\n    raise SystemExit(7)\nfinally:\n    print("finalized", flush=True)\n', encoding='utf-8')
    for args in [('with space', '中文'), ('cancel',)]:
        results = [subprocess.run([sys.executable, str(path), *args], cwd=tmp_path, capture_output=True, timeout=15)
                   for path in (target, scripts / 'cancel_probe.py')]
        assert results[0].returncode == results[1].returncode
        assert results[0].stdout == results[1].stdout
        assert b'finalized' in results[1].stdout
        if 'cancel' in args:
            assert b'KeyboardInterrupt' in results[1].stderr
        else:
            assert results[1].returncode == 7


@pytest.mark.parametrize('module_name,search_root,package', [
    ('inspect_spine_bundle', 'scripts', 'scripts'),
    ('scripts.inspect_spine_bundle', '.', 'scripts'),
    ('astrbot_plugin_nikke.scripts.inspect_spine_bundle', '..', 'astrbot_plugin_nikke.scripts'),
])
def test_legacy_import_from_other_directory(tmp_path, module_name, search_root, package):
    atlas = tmp_path / 'sample.atlas'
    atlas.write_text('texture.png\nsize: 8, 8\n', encoding='utf-8')
    (tmp_path / 'texture.png').write_bytes(b'')
    skeleton = tmp_path / 'sample.json'
    skeleton.write_text('{"skeleton": {"spine": "4.2.1"}}', encoding='utf-8')
    code = '''
import importlib
from pathlib import Path
import json
import sys
sys.path.insert(0, sys.argv[1])
module = importlib.import_module(sys.argv[2])
implementation = importlib.import_module(sys.argv[3] + '.spine.inspect_spine_bundle')
assert module is implementation
assert module.inspect is implementation.inspect
assert module._binary_spine_version is implementation._binary_spine_version
print(json.dumps(module.inspect(Path(sys.argv[4]), Path(sys.argv[5]), '4.2')))
'''
    result = subprocess.run(
        [sys.executable, '-c', code, str((PLUGIN_ROOT / search_root).resolve()),
         module_name, package, str(atlas), str(skeleton)],
        cwd=tmp_path, capture_output=True, text=True, encoding='utf-8', timeout=15,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'VERSION_MATCH'
    assert report['major_minor'] == '4.2'
    assert report['missing_pages'] == 0


@pytest.mark.parametrize('name,group', [('architecture_metrics','audit'), ('mirror_blablalink_assets','assets'), ('spine_batch_validation','spine'), ('backup_nikke_data','operations'), ('preview_t2i_frontend','preview'), ('inspect_spine_bundle','spine')])
@pytest.mark.parametrize('argument', ['--help', '--no-such-argument'])
def test_legacy_cli_matches_grouped_entry_from_other_directory(tmp_path, name, group, argument):
    results = []
    for path in [PLUGIN_ROOT / f'scripts/{name}.py', PLUGIN_ROOT / f'scripts/{group}/{name}.py']:
        result = subprocess.run([sys.executable, str(path), argument], cwd=tmp_path, capture_output=True, timeout=45)
        # argparse 的程序名一致，帮助、错误和退出状态须一致。
        results.append((result.returncode, result.stdout, result.stderr))
    assert results[0] == results[1]
    assert results[0][0] == (0 if argument == '--help' else 2)


def test_ci_fixture_provenance_and_hashes():
    manifest = json.loads((PLUGIN_ROOT / 'tests/fixtures/repository_organization_sources.json').read_text(encoding='utf-8'))
    for record in manifest:
        path = PLUGIN_ROOT / record['fixture']
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == record['sha256']
        assert record['source'].startswith('docs/archive/evidence/')
        assert len(record['source_commit']) == 40
