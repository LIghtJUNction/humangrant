#!/usr/bin/env python3
"""Local skills, document links, schema refs, prompt and SVG source checks. No network."""
from __future__ import annotations
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator
from markdown_it import MarkdownIt
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from sync_prompt import sync  # noqa: E402


class Failure(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)


def local_reference(source: Path, reference: str, root: Path = ROOT) -> None:
    parsed = urlsplit(reference)
    if parsed.scheme or reference.startswith(('#','//')):
        return
    path = unquote(parsed.path)
    if not path:
        return
    destination = (source.parent/path).resolve()
    require(destination.is_relative_to(root.resolve()),f'{source}: reference escapes repository: {reference}')
    require(destination.exists(),f'{source.relative_to(root)}: missing {reference}')
    if parsed.fragment and destination.suffix=='.json':
        value = json.loads(destination.read_text())
        for segment in unquote(parsed.fragment).lstrip('/').split('/'):
            segment = segment.replace('~1','/').replace('~0','~')
            require(isinstance(value,dict) and segment in value,f'Unresolved JSON pointer: {reference}')
            value = value[segment]


def walk_refs(value, source: Path, root: Path) -> None:
    if isinstance(value,dict):
        for key, child in value.items():
            if key=='$ref' and not child.startswith('#'):
                local_reference(source,child,root)
            else:
                walk_refs(child,source,root)
    elif isinstance(value,list):
        for child in value:
            walk_refs(child,source,root)


def check(root: Path = ROOT) -> dict[str,int]:
    sync(root,check=True)
    markdown = MarkdownIt('commonmark',{'html':True})
    count = 0
    for path in sorted(root.rglob('*.md')):
        if any(part in {'.git','.pytest_cache','.venv','target','verification-local','node_modules'} for part in path.relative_to(root).parts):
            continue
        text = path.read_text(encoding='utf-8')
        count += 1
        for token in markdown.parse(text):
            if token.type in {'html_block','html_inline'}:
                for link in re.findall(r'(?:src|href)="([^"]+)"',token.content):
                    local_reference(path,link,root)
            for child in token.children or []:
                if child.type=='link_open':
                    local_reference(path,child.attrGet('href'),root)
                elif child.type=='image':
                    local_reference(path,child.attrGet('src'),root)
                elif child.type=='html_inline':
                    for link in re.findall(r'(?:src|href)="([^"]+)"',child.content):
                        local_reference(path,link,root)
    for name in ('humangrant-integrate','humangrant-use'):
        path = root/'skills'/name/'SKILL.md'
        text = path.read_text(encoding='utf-8')
        require(text.startswith('---\n'),f'{name}: YAML frontmatter required')
        pieces = text.split('---\n',2)
        require(len(pieces)==3,f'{name}: unterminated frontmatter')
        metadata = yaml.safe_load(pieces[1])
        require(metadata.get('name')==name,f'{name}: name must match directory')
        require(bool(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name)) and len(name)<=64,f'{name}: invalid name')
        description = metadata.get('description','')
        require(isinstance(description,str) and 1<=len(description)<=1024 and 'Use when' in description,f'{name}: explain purpose and trigger')
        require(len(text.splitlines())<500,f'{name}: move details to references')
        require((path.parent/'references').is_dir(),f'{name}: reference instructions required')
        for document in path.parent.rglob('*.md'):
            contents = document.read_text()
            for command_path in re.findall(r'\bpython\s+((?:clients|scripts|examples)/[A-Za-z0-9_/-]+\.py)',contents):
                require((root/command_path).is_file(),f'{name}: nonexistent command {command_path}')
            for source_path in re.findall(r'`((?:src|spec|docs|schemas|clients|examples|tests)/[^`\s]+\.(?:rs|md|json|yaml|py))`',contents):
                require((root/source_path).is_file(),f'{name}: nonexistent reference {source_path}')
    schema_path = root/'schemas/protocol.json'
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    api_path = root/'openapi.yaml'
    api = yaml.safe_load(api_path.read_text())
    require(api['openapi']=='3.1.0','OpenAPI 3.1 is required')
    walk_refs(api,api_path,root)
    operation_ids = []
    for route, methods in api['paths'].items():
        for method, operation in methods.items():
            if method not in {'get','post','put','delete','patch'}:
                continue
            operation_ids.append(operation['operationId'])
            parameters = {p['name'] for p in operation.get('parameters',[]) if p.get('in')=='path'}
            require(parameters==set(re.findall(r'{([^}]+)}',route)),f'Path parameters inconsistent: {method} {route}')
    require(len(operation_ids)==len(set(operation_ids)),'Duplicate OpenAPI operationId')
    for name in ('continue-with-human-beings.svg','continue-with-human-beings-dark.svg'):
        asset = ET.fromstring((root/'assets'/name).read_text())
        texts = [node.text for node in asset.iter() if node.tag.endswith('}text')]
        require('Continue with human beings' in texts,f'{name}: fixed visible button label is missing')
        require(asset.attrib.get('viewBox')=='0 0 368 64',f'{name}: unexpected dimensions')
    readme=(root/'README.md').read_text()
    require('让 AI 为你的项目接入 HumanGrant' in readme[:2500],'Integration heading must be at the top')
    require('assets/continue-with-human-beings.svg' in readme[:2500],'README must show the button')
    require(not re.search(r'shields\.io|codecov\.io|badge\.svg',readme),'Unverified badge is not allowed')
    require((root/'AGENTS.md').is_file(),'AGENTS.md required')
    for path in root.rglob('*.rs'):
        if 'target' in path.parts:
            continue
        text=path.read_text()
        for relative in re.findall(r'include_str!\("([^"]+)"\)',text):
            local_reference(path,relative,root)
    return {'markdown_files':count,'skills':2,'openapi_operations':len(operation_ids),'button_variants':2}


if __name__=='__main__':
    try:
        print(json.dumps({'checks':'passed',**check()},ensure_ascii=False))
    except (OSError,ValueError,KeyError,TypeError) as error:
        print(f'Check failed: {error}',file=sys.stderr)
        sys.exit(1)
