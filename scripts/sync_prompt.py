#!/usr/bin/env python3
"""Synchronize the single-copy README prompt from its source and the actual Git origin."""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BEGIN = '<!-- BEGIN HUMANGRANT INTEGRATION PROMPT -->'
END = '<!-- END HUMANGRANT INTEGRATION PROMPT -->'
PLACEHOLDER = '[SOURCE_URL_NOT_CONFIGURED: set git remote origin, then run python scripts/sync_prompt.py]'


def remote(root: Path) -> str | None:
    result = subprocess.run(['git','remote','get-url','origin'],cwd=root,capture_output=True,text=True)
    if result.returncode:
        return None
    value = result.stdout.strip()
    if value.startswith('git@github.com:'):
        value = 'https://github.com/' + value.split(':',1)[1]
    if value.endswith('.git'):
        value = value[:-4]
    if not re.fullmatch(r'https://[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+', value):
        raise ValueError('Configure a credential-free HTTPS source URL or a GitHub SSH origin')
    return value


def sync(root: Path = ROOT, *, check: bool = False) -> None:
    prompt_path, readme_path = root/'prompts/integrate.md', root/'README.md'
    source = prompt_path.read_text(encoding='utf-8').rstrip() + '\n'
    origin = remote(root)
    # Source archives have no .git: retain the source URL recorded at initialization.
    if origin is not None or (root/'.git').exists():
        replacement = origin or PLACEHOLDER
        updated, count = re.subn(r'(HumanGrant 来源：\n)[^\n]+',lambda m:m.group(1)+replacement,source,count=1)
        if count != 1:
            raise ValueError('Missing source URL field in prompts/integrate.md')
    else:
        updated = source
    if re.search(r'(?m)^```',updated):
        raise ValueError('The self-contained prompt must not contain nested code fences')
    readme = readme_path.read_text(encoding='utf-8')
    if readme.count(BEGIN)!=1 or readme.count(END)!=1:
        raise ValueError('README must contain one integration-prompt region')
    start = readme.index(BEGIN)+len(BEGIN)
    stop = readme.index(END)
    block = '\n\n```text\n'+updated+'```\n\n'
    expected = readme[:start]+block+readme[stop:]
    if check:
        if source!=updated or readme!=expected:
            raise ValueError('Integration prompt is out of sync; run python scripts/sync_prompt.py')
    else:
        if source!=updated:
            prompt_path.write_text(updated,encoding='utf-8')
        if readme!=expected:
            readme_path.write_text(expected,encoding='utf-8')
    if origin is None and (root/'.git').exists():
        print('Source origin is missing; an explicit placeholder was written.',file=sys.stderr)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    try:
        sync(check=args.check)
        print('Integration prompt synchronization: OK')
    except (OSError, ValueError) as error:
        print(str(error),file=sys.stderr)
        sys.exit(1)
