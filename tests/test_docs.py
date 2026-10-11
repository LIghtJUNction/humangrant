from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from sync_prompt import BEGIN, END, DOCUMENTS, PLACEHOLDER, SKILL_PATH, sync
from check import check


def test_all_repository_documents_and_skills():
    assert check()['skills'] == 2


@pytest.mark.parametrize('prompt_name,readme_name', DOCUMENTS)
def test_readme_copyable_block_exactly_matches_source(prompt_name, readme_name):
    readme = (ROOT / readme_name).read_text(encoding='utf-8')
    region = readme.split(BEGIN)[1].split(END)[0]
    tokens = MarkdownIt().parse(region)
    assert len(tokens) == 1 and tokens[0].type == 'fence' and tokens[0].info == 'text'
    assert tokens[0].content == (ROOT / prompt_name).read_text(encoding='utf-8')
    assert len(tokens[0].content.splitlines()) == 1
    assert tokens[0].content.count('https://') == 1
    assert 'https://github.com/LIghtJUNction/humangrant' + SKILL_PATH in tokens[0].content
    assert (ROOT / SKILL_PATH.split('/blob/main/')[1]).is_file()


def copy_documents(destination):
    (destination / 'prompts').mkdir()
    for prompt_name, readme_name in DOCUMENTS:
        for name in (prompt_name, readme_name):
            shutil.copyfile(ROOT / name, destination / name)
    return destination


def isolated_repo(tmp_path):
    root = copy_documents(tmp_path)
    subprocess.run(['git', 'init', '-b', 'main'], cwd=root, check=True, capture_output=True)
    return root


def test_missing_origin_is_explicit_then_synchronizes(tmp_path):
    root = isolated_repo(tmp_path)
    sync(root)
    for prompt_name, _ in DOCUMENTS:
        assert PLACEHOLDER in (root / prompt_name).read_text(encoding='utf-8')
    subprocess.run(['git', 'remote', 'add', 'origin', 'https://github.com/LIghtJUNction/humangrant.git'],
                   cwd=root, check=True)
    sync(root)
    sync(root, check=True)
    for _, readme_name in DOCUMENTS:
        assert PLACEHOLDER not in (root / readme_name).read_text(encoding='utf-8')


@pytest.mark.parametrize('prompt_name,readme_name', DOCUMENTS)
def test_sync_detects_manual_readme_drift(tmp_path, prompt_name, readme_name):
    root = isolated_repo(tmp_path)
    sync(root)
    path = root / readme_name
    original = path.read_text(encoding='utf-8')
    path.write_text(original.replace('```text\n', '```text\nWRONG ', 1), encoding='utf-8')
    with pytest.raises(ValueError, match='out of sync'):
        sync(root, check=True)
    assert 'WRONG ' in path.read_text(encoding='utf-8')
    sync(root)
    assert path.read_text(encoding='utf-8') == original


def test_source_archive_keeps_recorded_source(tmp_path):
    sync(copy_documents(tmp_path), check=True)


@pytest.mark.parametrize('origin', (
    'https://github.com/example/humangrant.git',
    'git@github.com:example/humangrant.git',
))
def test_remote_change_updates_both_languages(tmp_path, origin):
    root = isolated_repo(tmp_path)
    subprocess.run(['git', 'remote', 'add', 'origin', origin], cwd=root, check=True)
    sync(root)
    sync(root, check=True)
    for prompt_name, readme_name in DOCUMENTS:
        for name in (prompt_name, readme_name):
            assert 'https://github.com/example/humangrant' + SKILL_PATH in (root / name).read_text(encoding='utf-8')


@pytest.mark.parametrize('replacement', (
    'No skill link\n',
    'Read https://example.test/instructions.md\n',
    'Read https://github.com/example/repo' + SKILL_PATH + '\nAnother sentence.\n',
    'Read ``` https://github.com/example/repo' + SKILL_PATH + '\n',
))
def test_sync_rejects_invalid_prompts_without_partial_writes(tmp_path, replacement):
    root = isolated_repo(tmp_path)
    (root / DOCUMENTS[1][0]).write_text(replacement, encoding='utf-8')
    before = {name: (root / name).read_bytes() for pair in DOCUMENTS for name in pair}
    with pytest.raises(ValueError):
        sync(root)
    assert before == {name: (root / name).read_bytes() for name in before}


def test_default_english_and_chinese_language_switches():
    english = (ROOT / 'README.md').read_text(encoding='utf-8')
    chinese = (ROOT / 'README.zh-CN.md').read_text(encoding='utf-8')
    assert 'href="README.zh-CN.md"' in english[:1000]
    assert 'href="README.md"' in chinese[:1000]
    assert english.index('## Add to your project') < english.index(BEGIN)
    assert chinese.index('## 让 AI 为你的项目接入 HumanGrant') < chinese.index(BEGIN)
    for text in (english, chinese):
        assert 'srcset="assets/continue-with-human-beings-dark.svg"' in text
        assert 'src="assets/continue-with-human-beings.svg"' in text
        assert 'assets/wordmark.svg' in text
        assert len(text.encode('utf-8')) < 6000
        for removed in ('docs/verification.md', '尚未推送', '## Boundaries', '## Progress', '## Disclaimer'):
            assert removed not in text


def test_badges_describe_real_repository_contents():
    expected = {
        'protocol': ('Protocol: 0.1', 'spec/v0.1.md'),
        'rust': ('Built with: Rust', 'Cargo.toml'),
        'sqlite': ('Storage: SQLite', 'migrations/0001.sql'),
        'openapi': ('API: OpenAPI 3.1', 'openapi.yaml'),
        'skills': ('Agent Skills: 2', 'skills/humangrant-integrate/SKILL.md'),
        'license': ('License: MIT', 'LICENSE'),
    }
    for name, (title, source) in expected.items():
        svg = ET.parse(ROOT / 'assets' / 'badges' / f'{name}.svg').getroot()
        assert svg.find('{http://www.w3.org/2000/svg}title').text == title
        assert (ROOT / source).is_file()
    assert len(list((ROOT / 'skills').glob('*/SKILL.md'))) == 2
    assert 'MIT License' in (ROOT / 'LICENSE').read_text()
    for _, readme_name in DOCUMENTS:
        readme = (ROOT / readme_name).read_text(encoding='utf-8')
        assert 'actions/workflows/ci.yml/badge.svg?branch=main' in readme
        assert 'codecov' not in readme and 'coverage-' not in readme


def test_html_dark_image_references_are_checked(tmp_path):
    from check import Failure
    root = tmp_path / 'repo'
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('.git', '.pytest_cache', '__pycache__'))
    path = root / 'README.md'
    path.write_text(path.read_text(encoding='utf-8').replace(
        'srcset="assets/continue-with-human-beings-dark.svg"', 'srcset="assets/missing-dark.svg"',
    ), encoding='utf-8')
    with pytest.raises(Failure, match='missing assets/missing-dark.svg'):
        check(root)


def test_ci_contains_required_commands():
    workflow = (ROOT / '.github/workflows/ci.yml').read_text()
    for command in ['cargo fmt --check', 'cargo clippy --all-targets -- -D warnings', 'cargo test', 'cargo build',
                    'python -m pytest -q', 'python scripts/check.py', 'python scripts/sync_prompt.py --check',
                    'python scripts/e2e.py']:
        assert command in workflow
