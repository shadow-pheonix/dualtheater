-- Runs after demux track discovery, before audio decoder initialization.
mp.add_hook('on_preloaded', 50, function()
    local requested = mp.get_property('user-data/dualtheater-aid', 'auto')
    if requested == 'auto' then
        for _, track in ipairs(mp.get_property_native('track-list', {})) do
            if track.type == 'audio' and track.codec == 'truehd' then
                mp.set_property_number('aid', track.id)
                return
            end
        end
        -- The host reports a useful error; never choose a different codec silently.
        if not mp.get_property_native('user-data/dualtheater-diagnostic', false) then
            mp.set_property('aid', 'no')
        end
    else
        mp.set_property('aid', requested)
    end
end)
