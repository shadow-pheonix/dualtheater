"""Execute the shipped Lua selection hook in real mpv with synthetic metadata."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('DUALTHEATER_MPV'), 'Set DUALTHEATER_MPV for the real Lua policy test')
class AudioSelectionTests(unittest.TestCase):
    def test_default_ranking_languages_negative_metadata_and_manual_override(self):
        def track(ident, codec='truehd', **metadata):
            return dict(id=ident, type='audio', codec=codec, **metadata)
        cases = [
            {'tracks': [track(1, lang='hin', title='TrueHD Atmos'),
                        track(2, lang='eng', title='TrueHD Atmos')], 'expected': 2},
            {'tracks': [track(1, lang='hin', title='TrueHD Atmos'),
                        track(2, title='English.TrueHD.Atmos.7.1')], 'expected': 2},
            {'tracks': [track(1, lang='eng'), track(2, lang='tel', title='Atmos')], 'expected': 2},
            {'tracks': [track(1, lang='hin'), track(2, lang='en-US')], 'expected': 2},
            {'tracks': [track(1, lang='eng', title='no Atmos'),
                        track(2, lang='hin', title='Atmos')], 'expected': 2},
            {'tracks': [track(1, lang='en', title='without Dolby Atmos'),
                        track(2, lang='eng', title='Dolby Atmos')], 'expected': 2},
            {'tracks': [track(1, lang='en', title='Non-Atmos stereo'),
                        track(2, lang='en_GB', profile='Dolby TrueHD + Dolby Atmos')], 'expected': 2},
            {'tracks': [track(1, title='Hinglish Atmos'),
                        track(2, metadata={'LANGUAGE': 'eng', 'TITLE': 'Atmos'})], 'expected': 2},
            {'tracks': [track(1, 'eac3', lang='eng', title='Atmos'), track(2)], 'expected': 2},
            {'tracks': [track(1, 'ac3'), track(2, 'dts-hd'), track(3, 'eac3')], 'expected': 2},
            {'tracks': [track(1, lang='eng', title='Atmos'),
                        track(2, lang='hin', title='Atmos')], 'requested': '2', 'expected': '2'},
            {'tracks': [track(1, lang='eng', title='Atmos')], 'requested': 'no', 'expected': 'no'},
            {'tracks': [track(1, lang='eng', title='Atmos'), track(2, lang='eng', title='Atmos')], 'expected': 1},
            {'tracks': [track(1, 'aac')], 'expected': 'no'},
            {'tracks': [dict(id=1, type='video', codec='truehd', title='English Atmos'), track(2)], 'expected': 2},
        ]
        source = Path(__file__).resolve().parents[1] / 'host/select_audio.lua'
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'cases.json').write_text(json.dumps(cases), encoding='utf-8')
            script = folder / 'policy.lua'
            # Use the real interpreter and shipped hook; replace only mpv's
            # demux/control boundary so combinations need no copyrighted media.
            script.write_text('''local real_mp = mp
local utils = require 'mp.utils'
local base = ''' + json.dumps(folder.as_posix()) + '''
local success, problem = pcall(function()
local input = assert(io.open(base .. '/cases.json', 'rb'))
local cases = utils.parse_json(input:read('*a')); input:close()
local results = {}
for _, case in ipairs(cases) do
    local selected, hook
    local fake = {
        add_hook = function(_, _, callback) hook = callback end,
        get_property_native = function(key, default)
            if key == 'track-list' then return case.tracks end
            if key == 'user-data/dualtheater-aid' then return case.requested or 'auto' end
            if key == 'user-data/dualtheater-diagnostic' then return false end
            return default
        end,
        set_property = function(_, value) selected = value end,
        set_property_number = function(_, value) selected = value end,
    }
    local env = setmetatable({mp = fake}, {__index = _G})
    local chunk
    if setfenv then
        chunk = assert(loadfile(''' + json.dumps(source.as_posix()) + ''')); setfenv(chunk, env)
    else
        chunk = assert(loadfile(''' + json.dumps(source.as_posix()) + ''', 't', env))
    end
    chunk(); assert(hook); hook()
    results[#results + 1] = selected or false
end
local output = assert(io.open(base .. '/results.json', 'wb'))
output:write(utils.format_json(results)); output:close()
end)
if not success then
    local failure = assert(io.open(base .. '/error.txt', 'wb'))
    failure:write(tostring(problem)); failure:close()
end
real_mp.commandv('quit', 0)
''', encoding='utf-8')
            try:
                result = subprocess.run([os.environ['DUALTHEATER_MPV'], '--no-config', '--vo=null', '--ao=null',
                                         '--force-window=no', '--idle=yes', '--script=' + str(script)],
                                        capture_output=True, timeout=15)
            except subprocess.TimeoutExpired as error:
                self.fail(((error.stdout or b'') + (error.stderr or b'')).decode('utf-8', errors='replace'))
            self.assertTrue((folder / 'results.json').exists(),
                            (folder / 'error.txt').read_text() if (folder / 'error.txt').exists()
                            else (result.stdout + result.stderr).decode('utf-8', errors='replace'))
            self.assertEqual(result.returncode, 0)
            results = json.loads((folder / 'results.json').read_text(encoding='utf-8'))
            self.assertEqual(len(results), len(cases))
            for index, (case, selected) in enumerate(zip(cases, results)):
                with self.subTest(case=index): self.assertEqual(selected, case['expected'])
