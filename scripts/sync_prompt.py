#!/usr/bin/env python3
"""Sync the one-line English and Chinese README prompts with the Git origin."""
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
SKILL_PATH = '/blob/main/skills/humangrant-integrate/SKILL.md'
DOCUMENTS = (
    ('prompts/integrate.md', 'README.md'),
    ('prompts/integrate.zh-CN.md', 'README.zh-CN.md'),
)
LINK = re.compile(r'https://[A-Za-z0-9._/-]+' + re.escape(SKILL_PATH) + '|' + re.escape(PLACEHOLDER))


def remote(root: Path) -> str | None:
    result = subprocess.run(
        ['git', 'remote', 'get-url', 'origin'], cwd=root, capture_output=True, text=True,
    )
    if result.returncode:
        return None
    value = result.stdout.strip()
    if value.startswith('git@github.com:'):
        value = 'https://github.com/' + value.split(':', 1)[1]
    if value.endswith('.git'):
        value = value[:-4]
    if not re.fullmatch(r'https://[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+', value):
        raise ValueError('Configure a credential-free HTTPS source URL or a GitHub SSH origin')
    return value


def sync(root: Path = ROOT, *, check: bool = False) -> None:
    origin = remote(root)
    changes: list[tuple[Path, str]] = []
    for prompt_name, readme_name in DOCUMENTS:
        prompt_path, readme_path = root / prompt_name, root / readme_name
        source = prompt_path.read_text(encoding='utf-8')
        if len(source.splitlines()) != 1 or '```' in source:
            raise ValueError(f'{prompt_name}: expected one line without code fences')
        if len(LINK.findall(source)) != 1:
            raise ValueError(f'{prompt_name}: expected one integration skill link')
        updated = source.rstrip() + '\n'
        # Archives keep their recorded link; a Git checkout uses its actual origin.
        if origin is not None or (root / '.git').exists():
            replacement = origin + SKILL_PATH if origin else PLACEHOLDER
            updated = LINK.sub(lambda _: replacement, updated, count=1)
        readme = readme_path.read_text(encoding='utf-8')
        if readme.count(BEGIN) != 1 or readme.count(END) != 1:
            raise ValueError(f'{readme_name}: expected one integration-prompt region')
        start, stop = readme.index(BEGIN) + len(BEGIN), readme.index(END)
        if stop < start:
            raise ValueError(f'{readme_name}: reversed prompt markers')
        block = '\n\n```text\n' + updated + '```\n\n'
        expected = readme[:start] + block + readme[stop:]
        for path, actual, wanted in (
            (prompt_path, source, updated), (readme_path, readme, expected),
        ):
            if actual != wanted:
                changes.append((path, wanted))
    if check and changes:
        raise ValueError('Integration prompts are out of sync; run python scripts/sync_prompt.py')
    for path, content in changes:
        path.write_text(content, encoding='utf-8')
    if origin is None and (root / '.git').exists():
        print('Source origin is missing; configure origin and run the sync script.', file=sys.stderr)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        sync(check=args.check)
        print('Integration prompt synchronization: OK')
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
