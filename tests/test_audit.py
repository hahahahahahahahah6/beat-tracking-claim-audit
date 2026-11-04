import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from beat_tracking_claim_audit.audit import audit, claims, evidence, main
from beat_tracking_claim_audit.phrases import BEATTRACKING, NOBEATTRACKING, GENERIC

EXPECTED_POSITIVE = ('beat tracking', 'tracks beats', 'tracks the beat', 'track beats', 'beat tracker', 'beat trackers', 'detects beats', 'detect beats', 'beat detection', 'finds beats', 'find beats', 'extracts beats', 'extract beats', 'identifies beats', 'identify beats', 'locates beats', 'locate beats', 'finds beat times', 'find beat times', 'beat times', 'beat positions', 'beat locations', 'beat grid', 'beat map', 'beat sequence', 'beat timestamps', 'beat estimation', 'estimates beats', 'estimate beats', 'beat extraction', 'extracts beat times', 'extract beat times', 'detects beat positions', 'detect beat positions', 'tracks beat positions', 'beat following', 'follows beats', 'follow beats', 'beat tracking algorithm', 'automatic beat tracking', 'real-time beat tracking', 'realtime beat tracking', 'online beat tracking', 'beat tracking system', 'beat tracking feature', 'beat tracking support', 'beat tracking capability', 'supports beat tracking', 'provides beat tracking', 'performs beat tracking')
EXPECTED_NEGATIVE = ('does not track beats', 'do not track beats', "doesn't track beats", "don't track beats", 'no beat tracking', 'without beat tracking', 'never tracks beats', 'does not detect beats', 'do not detect beats', 'no beat detection', 'without beat detection', 'does not find beats', 'no beat tracker', 'without a beat tracker', 'does not extract beats', 'beat tracking not supported', 'beat tracking unsupported', 'no beat tracking support', 'does not identify beats', 'never detects beats', 'lacks beat tracking', 'missing beat tracking', 'beat tracking disabled', 'no beat times')
EXPECTED_GENERIC = ('beat_track', 'track_beats', 'detect_beats', 'find_beats', 'get_beats', 'extract_beats', 'beat_tracker', 'track_beat', 'detect_beat', 'find_beat', 'estimate_beats', 'beat_times', 'get_beat_times', 'extract_beat_times', 'detect_beat_times', 'beat_tracking', 'track_beats_in_audio', 'find_beat_times', 'compute_beats', 'predict_beats', 'beat_sequence', 'get_beat_sequence', 'extract_beats_from_audio', 'beat_track_times')

class AuditTests(unittest.TestCase):
    def project(self, files):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        return root

    def cli(self, root, *options):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(['audit', str(root), '--json', *options])
        return code, json.loads(out.getvalue())

    def test_phrase_oracle(self):
        self.assertEqual(BEATTRACKING, EXPECTED_POSITIVE)
        self.assertEqual(NOBEATTRACKING, EXPECTED_NEGATIVE)
        self.assertEqual((len(BEATTRACKING), len(NOBEATTRACKING)), (50, 24))

    def test_generic_oracle(self):
        self.assertEqual(GENERIC, EXPECTED_GENERIC)
        self.assertEqual(len(GENERIC), 24)

    def test_matching(self):
        self.assertEqual(claims('does not track beats'), ([], ['does not track beats']))
        self.assertEqual(claims('automatic beat tracking'), (['automatic beat tracking'], []))
        self.assertEqual(claims('```text\nbeat tracking\n```'), ([], []))
        self.assertEqual(claims('`beat tracking`'), (['beat tracking'], []))
        self.assertEqual(claims('BEAT TRACKING'), (['beat tracking'], []))
        self.assertEqual(claims('beat-tracking'), ([], []))
        self.assertEqual(claims('xtrack beatsx')[0], ['track beats'])

    def test_cli_fixtures(self):
        cases = [({'README.md':'beat tracking', 'app.py':'e.track_beats()'}, 0, None, None),
                 ({'README.md':'beat tracking'}, 2, 'documented-beat-tracking-claim-false', 'HIGH'),
                 ({'tests/fixture.md':'beat tracking'}, 0, 'documented-beat-tracking-claim-false', 'MEDIUM'),
                 ({'README.md':'no beat tracking', 'app.py':'e.track_beats()'}, 2, 'documented-no-beat-tracking-claim-false', 'HIGH'),
                 ({'README.md':'An application.'}, 0, None, None)]
        for files, expected, identifier, severity in cases:
            with self.subTest(files=files):
                root = self.project(files)
                code, result = self.cli(root)
                self.assertEqual(code, expected)
                if identifier:
                    item = result['findings'][0]
                    self.assertEqual((item['id'], item['severity']), (identifier, severity))
                    self.assertEqual(item['verdict'], 'FAIL')
                    self.assertTrue(item['message'])
                else:
                    self.assertEqual(result['verdict'], 'PASS')
                    self.assertEqual(result['findings'], [])
                if severity == 'MEDIUM':
                    self.assertEqual(self.cli(root, '--fail-on', 'medium')[0], 2)

    def test_ignore_verbose_scope(self):
        root = self.project({'docs/a.md':'beat tracking', 'docs/b.md':'beat tracking', 'other.md':'beat tracking'})
        self.assertEqual(self.cli(root)[0], 2)
        code, result = self.cli(root, '--ignore', 'docs/a', '--ignore', 'docs/b', '--verbose')
        self.assertEqual(code, 0)
        self.assertIn('scope', result)
        self.assertTrue(result['decisions'])
        root = self.project({'README.md':'beat tracking', '.venv/a.py':'e.track_beats()', '.git/a.py':'e.track_beats()', '__pycache__/a.py':'e.track_beats()'})
        self.assertEqual(self.cli(root)[0], 2)
        root = self.project({'README.md':'beat tracking', 'docs/a.py':'e.track_beats()'})
        self.assertEqual(self.cli(root)[0], 0)
        self.assertEqual(self.cli(root, '--ignore', 'docs')[0], 2)

    def test_split_modules(self):
        for ctor in ('from aubio import tempo\nx=tempo()', 'from madmom.features.beats import BeatTrackingProcessor\nx=BeatTrackingProcessor()'):
            root = self.project({'README.md':'beat tracking','a.py':ctor,'b.py':'x()'})
            self.assertEqual(self.cli(root)[0], 2)

    def test_usage_version_module(self):
        for args, expected in [(['--version'], 0), (['--help'], 0), (['--bad'], 1), (['audit','/does-not-exist'], 1), (['audit','--fail-on','low'], 1)]:
            proc = subprocess.run([sys.executable, '-m', 'beat_tracking_claim_audit', *args], text=True, capture_output=True)
            self.assertEqual(proc.returncode, expected, proc.stderr)
            if args == ['--version']:
                self.assertEqual(proc.stdout.strip(), '0.1.0')

    def test_default_repo(self):
        self.assertEqual(main(['audit', '--ignore', 'tests']), 0)

    def test_self_audit(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(claims((root / 'README.md').read_text()), ([], []))
        self.assertEqual(audit(root)['verdict'], 'PASS')


def case(name, source, expected):
    def test(self):
        self.assertEqual(evidence(source), expected, source)
    setattr(AuditTests, 'test_' + name, test)

for index, phrase in enumerate(EXPECTED_POSITIVE):
    def test(self, phrase=phrase):
        self.assertEqual(claims(phrase), ([phrase], []))
    setattr(AuditTests, 'test_phrase_positive_%02d' % index, test)
for index, phrase in enumerate(EXPECTED_NEGATIVE):
    def test(self, phrase=phrase):
        self.assertEqual(claims(phrase), ([], [phrase]))
    setattr(AuditTests, 'test_phrase_negative_%02d' % index, test)

for name in EXPECTED_GENERIC:
    for style, source in [('attribute','engine.'+name+'()'), ('from','from engine import '+name+'\n'+name+'()'), ('alias','from engine import '+name+' as f\nf()'), ('unbound',name+'()'), ('reference','engine.'+name), ('shadow','def '+name+'(): pass\nengine.'+name+'()'), ('class_shadow','from engine import '+name+'\nclass '+name+': pass\n'+name+'()')]:
        case('generic_'+name+'_'+style, source, style in ('attribute','from','alias'))

for name in ('beat_track','plp'):
    for style, source in [('full','import librosa\nlibrosa.beat.'+name+'()'), ('module_alias','import librosa.beat as lb\nlb.'+name+'()'), ('from','from librosa.beat import '+name+'\n'+name+'()'), ('alias','from librosa.beat import '+name+' as f\nf()'), ('chain','from librosa import beat as b\nb.'+name+'()')]:
        case('librosa_'+name+'_'+style, source, True)

for namespace in ('standard','streaming'):
    for name in ('RhythmExtractor2013','BeatTrackerMultiFeature','BeatTrackerDegara'):
        for style, source in [('full','import essentia.'+namespace+'\nessentia.'+namespace+'.'+name+'()'), ('module','import essentia.'+namespace+' as es\nes.'+name+'()'), ('from','from essentia.'+namespace+' import '+name+'\n'+name+'()'), ('alias','from essentia.'+namespace+' import '+name+' as C\nC()')]:
            case('essentia_'+namespace+'_'+name+'_'+style, source, True)

for module, name in [('madmom.features.beats','BeatTrackingProcessor'), ('madmom.features.beats','DBNBeatTrackingProcessor'), ('aubio','tempo')]:
    for style, prefix, call in [('full','import '+module,module+'.'+name), ('module','import '+module+' as m','m.'+name), ('from','from '+module+' import '+name,name), ('alias','from '+module+' import '+name+' as C','C')]:
        case('pair_'+name+'_'+style, prefix+'\nx='+call+'()\nx(audio)', True)
        case('pair_'+name+'_'+style+'_chained', prefix+'\n'+call+'()(audio)', True)
        case('pair_'+name+'_'+style+'_alone', prefix+'\nx='+call+'()', False)
        case('pair_'+name+'_'+style+'_shadow', prefix+'\nclass '+name+': pass\nx='+call+'()\nx(audio)', False)
    case('pair_'+name+'_chained_original_shadow', 'from '+module+' import '+name+' as C\nclass '+name+': pass\nC()(audio)', False)
    case('pair_'+name+'_alias_shadow', 'from '+module+' import '+name+' as C\nclass C: pass\nx=C()\nx(audio)', False)

NOT_EVIDENCE = [
 'import librosa.beat', 'from librosa.beat import beat_track', 'from essentia.standard import RhythmExtractor2013',
 'from madmom.features.beats import BeatTrackingProcessor', 'from aubio import tempo',
 'import librosa\nlibrosa.beat.tempo(y)', 'engine.estimate_tempo()', 'engine.estimate_bpm()',
 'import librosa\nlibrosa.onset.onset_detect(y)', 'engine.detect_onsets()',
 'from madmom.features.downbeats import DBNDownBeatTrackingProcessor\nx=DBNDownBeatTrackingProcessor()\nx(audio)',
 'engine.classify_chord()', 'engine.classify_key()', 'engine.estimate_pitch()', 'engine.classify_genre()',
 '"beat_track()"', '# engine.track_beats()', '"""engine.track_beats()"""',
 'from librosa.beat import beat_track\nbeat_track',
 'from librosa.beat import beat_track\ndef beat_track(): pass\nbeat_track()',
 'from librosa.beat import beat_track as b\ndef b(): pass\nb()',
 'from essentia.standard import RhythmExtractor2013\nclass RhythmExtractor2013: pass\nRhythmExtractor2013()',
 'subprocess.run(["beat-tracker", "audio.wav"])', 'engine.metronome()', 'engine.mix_beats()',
 'engine.classify()', 'engine.extract_embedding()', 'engine.embed()', 'bad syntax !'
]
for index, source in enumerate(NOT_EVIDENCE):
    case('rejection_%02d' % index, source, False)

if __name__ == '__main__':
    unittest.main()
