-- Source-time observations, not IPC delivery time. Audio remains at 1x.
local mp = require 'mp'
mp.register_script_message('dualtheater-sample', function(request)
    local before = mp.get_time()
    local pts = mp.get_property_number('audio-pts')
    local after = mp.get_time()
    mp.commandv('script-message', 'dualtheater-audio-sample', request,
        tostring(before), tostring(after), pts and tostring(pts) or 'unavailable')
end)
