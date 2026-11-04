"""Deterministic, offline documentation and AST inspection."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys
from .phrases import BEATTRACKING, NOBEATTRACKING, GENERIC


def claims(text):
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line.replace('`', ''))
    text = '\n'.join(lines).lower()

    def remove(vocabulary):
        nonlocal text
        found = []
        for phrase in sorted(vocabulary, key=len, reverse=True):
            while phrase in text:
                start = text.index(phrase)
                found.append(phrase)
                text = text[:start] + ' ' * len(phrase) + text[start + len(phrase):]
        return found
    negative = remove(NOBEATTRACKING)
    positive = remove(BEATTRACKING)
    return positive, negative


def evidence(source):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    aliases = {}
    shadow = {n.name for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = node.module + '.' + item.name

    def resolve(node):
        if isinstance(node, ast.Name):
            if node.id in shadow:
                return ''
            resolved = aliases.get(node.id, node.id)
            return '' if any(part in shadow for part in resolved.split('.')) else resolved
        if isinstance(node, ast.Attribute):
            if node.attr in shadow:
                return ''
            base = resolve(node.value)
            return base + '.' + node.attr if base else ''
        return ''

    def constructor(call):
        if not isinstance(call, ast.Call):
            return False
        name = resolve(call.func)
        return (name in ('aubio.tempo',) or
                name in tuple('madmom.features.beats.' + n for n in
                              ('BeatTrackingProcessor', 'DBNBeatTrackingProcessor')))

    def identity(node):
        if isinstance(node, ast.Name):
            return node.id if node.id not in shadow else ''
        if isinstance(node, ast.Attribute):
            base = identity(node.value)
            return base + '.' + node.attr if base else ''
        return ''

    instances = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and constructor(node.value):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, (ast.Name, ast.Attribute)):
                    instances.add(identity(target))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = resolve(node.func)
        leaf = name.rsplit('.', 1)[-1]
        if name in ('librosa.beat.beat_track', 'librosa.beat.plp'):
            return True
        if name in tuple('essentia.' + namespace + '.' + cls
                         for namespace in ('standard', 'streaming')
                         for cls in ('RhythmExtractor2013', 'BeatTrackerMultiFeature', 'BeatTrackerDegara')):
            return True
        if leaf in GENERIC and (isinstance(node.func, ast.Attribute) or
                                isinstance(node.func, ast.Name) and node.func.id in aliases):
            return True
        if (identity(node.func) and identity(node.func) in instances) or constructor(node.func):
            return True
    return False


def audit(repo, ignore=(), fail_on='high', verbose=False):
    root = Path(repo)
    if not root.is_dir():
        raise OSError('Repository must be an existing directory: ' + str(root))
    documents, sources, decisions, evidence_paths = [], [], [], []
    positive, negative, test_positive = [], [], []
    excluded = {'.git', '__pycache__', '.venv', 'venv', 'env', '.env'}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in excluded and
                         not (Path(directory) / d / 'pyvenv.cfg').exists() and
                         not (Path(directory) / d).is_symlink())
        for filename in sorted(files):
            path = Path(directory) / filename
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or any(relative.startswith(prefix) for prefix in ignore):
                decisions.append(relative + ': skipped')
                continue
            parts = path.relative_to(root).parts
            doc = relative == 'README.md' or (parts[0] == 'docs' and path.suffix == '.md')
            test = 'tests' in parts[:-1]
            if doc or test:
                if doc or path.suffix in ('.md', '.py', '.txt', '.rst'):
                    p, n = claims(path.read_text(encoding='utf-8'))
                    if doc:
                        documents.append(relative)
                        positive.extend(p)
                        negative.extend(n)
                    elif test:
                        test_positive.extend(p)
                    decisions.append(relative + ': positive=%d negative=%d' % (len(p), len(n)))
            if path.suffix == '.py':
                sources.append(relative)
                present = evidence(path.read_text(encoding='utf-8'))
                if present:
                    evidence_paths.append(relative)
                decisions.append(relative + ': evidence=' + str(present))
    findings = []
    def finding(identifier, severity, message):
        findings.append(dict(id=identifier, severity=severity, verdict='FAIL', message=message))
    if positive and not evidence_paths:
        finding('documented-beat-tracking-claim-false', 'HIGH', 'Documentation claim has no matching Python call evidence.')
    elif test_positive and not positive and not evidence_paths:
        finding('documented-beat-tracking-claim-false', 'MEDIUM', 'Claim occurs only under tests and has no matching Python call evidence.')
    if negative and evidence_paths:
        finding('documented-no-beat-tracking-claim-false', 'HIGH', 'Documentation denial conflicts with Python call evidence.')
    failed = any(f['severity'] == 'HIGH' or fail_on.lower() == 'medium' for f in findings)
    result = dict(verdict='FAIL' if failed else 'PASS', findings=findings,
                  docs=documents, sources=sources, evidence=evidence_paths)
    if verbose:
        result['scope'] = 'README.md, docs/**/*.md, tests claims, and all Python sources'
        result['decisions'] = decisions
    return result


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--version', action='version', version='0.1.0')
    sub = parser.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('audit')
    scan.add_argument('repo', nargs='?', default='.')
    scan.add_argument('--json', action='store_true')
    scan.add_argument('--verbose', action='store_true')
    scan.add_argument('--ignore', action='append', default=[])
    scan.add_argument('--fail-on', choices=('high', 'medium'), default='high')
    try:
        args = parser.parse_args(argv)
        result = audit(args.repo, args.ignore, args.fail_on, args.verbose)
        if args.json:
            print(json.dumps(result, sort_keys=True))
        else:
            print(result['verdict'])
            for item in result['findings']:
                print('{severity} {id}: {message}'.format(**item))
            if args.verbose:
                print(result['scope'])
                print('\n'.join(result['decisions']))
        return 2 if result['verdict'] == 'FAIL' else 0
    except (ValueError, OSError, UnicodeError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 1
