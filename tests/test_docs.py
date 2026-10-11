import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from markdown_it import MarkdownIt

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from sync_prompt import BEGIN, END, PLACEHOLDER, sync
from check import check


def test_all_repository_documents_and_skills():
    assert check()['skills']==2


def test_readme_copyable_block_exactly_matches_source():
    readme=(ROOT/'README.md').read_text()
    region=readme.split(BEGIN)[1].split(END)[0]
    tokens=MarkdownIt().parse(region)
    assert len(tokens)==1 and tokens[0].type=='fence' and tokens[0].info=='text'
    assert tokens[0].content==(ROOT/'prompts/integrate.md').read_text()
    assert 'HumanGrant Protocol 0.1 Draft' in tokens[0].content
    assert 'https://github.com/LIghtJUNction/humangrant' in tokens[0].content


def isolated_repo(tmp_path):
    (tmp_path/'prompts').mkdir()
    shutil.copyfile(ROOT/'prompts/integrate.md',tmp_path/'prompts/integrate.md')
    shutil.copyfile(ROOT/'README.md',tmp_path/'README.md')
    subprocess.run(['git','init','-b','main'],cwd=tmp_path,check=True,capture_output=True)
    return tmp_path


def test_missing_origin_is_explicit_then_synchronizes(tmp_path):
    root=isolated_repo(tmp_path)
    sync(root)
    assert PLACEHOLDER in (root/'prompts/integrate.md').read_text()
    subprocess.run(['git','remote','add','origin','https://github.com/LIghtJUNction/humangrant.git'],cwd=root,check=True)
    sync(root)
    sync(root,check=True)
    assert PLACEHOLDER not in (root/'README.md').read_text()


def test_sync_detects_manual_readme_drift(tmp_path):
    root=isolated_repo(tmp_path)
    sync(root)
    path=root/'README.md'
    path.write_text(path.read_text().replace('请为当前项目接入 HumanGrant','WRONG',1))
    with pytest.raises(ValueError):
        sync(root,check=True)


def test_source_archive_keeps_recorded_source(tmp_path):
    (tmp_path/'prompts').mkdir()
    shutil.copyfile(ROOT/'prompts/integrate.md',tmp_path/'prompts/integrate.md')
    shutil.copyfile(ROOT/'README.md',tmp_path/'README.md')
    sync(tmp_path,check=True)


def test_ci_contains_required_commands():
    workflow=(ROOT/'.github/workflows/ci.yml').read_text()
    for command in ['cargo fmt --check','cargo clippy --all-targets -- -D warnings','cargo test','cargo build',
                    'python -m pytest -q','python scripts/check.py','python scripts/sync_prompt.py --check','python scripts/e2e.py']:
        assert command in workflow
