local function words(value)
    return string.lower(tostring(value or '')):gsub('[%p_]+', ' '):gsub('%s+', ' ')
end

local function mentions(text, word)
    return text:match('%f[%w]' .. word .. '%f[%W]') ~= nil
end

local function preference(track)
    local codec = string.lower(track.codec or ''):gsub('_', '-')
    if codec == 'truehd' then
        local metadata = track.metadata or {}
        local title = words((track.title or '') .. ' ' .. (metadata.title or metadata.TITLE or ''))
        local profile = words(track['codec-profile'] or track.profile)
        local description = title .. ' ' .. profile
        local atmos = mentions(description, 'atmos')
        for _, negative in ipairs({'no atmos', 'no dolby atmos', 'without atmos',
                                   'without dolby atmos', 'non atmos', 'non dolby atmos'}) do
            if mentions(description, negative) then atmos = false end
        end
        local language = string.lower(track.lang or track.language or metadata.language or metadata.LANGUAGE or '')
        local english = language == 'eng' or language == 'en'
            or language:match('^en[-_]') ~= nil or language == 'english' or mentions(title, 'english')
        if atmos then return english and 1 or 2 end
        return english and 3 or 4
    end
    local priority = { ['dts-hd'] = 5, ['dts-hd-ma'] = 5, eac3 = 6, ac3 = 7, dts = 8 }
    return priority[codec]
end

-- Runs after demux track discovery, before audio decoder initialization.
mp.add_hook('on_preloaded', 50, function()
    -- user-data is a native JSON tree: get_property serializes strings with
    -- quotes, turning an id such as 2 into the invalid option value '"2"'.
    local requested = mp.get_property_native('user-data/dualtheater-aid', 'auto')
    if requested == 'auto' then
        local selected, rank
        for _, track in ipairs(mp.get_property_native('track-list', {})) do
            if track.type == 'audio' then
                local candidate = preference(track)
                if candidate and (not rank or candidate < rank) then
                    selected, rank = track.id, candidate
                end
            end
        end
        if selected then
            mp.set_property_number('aid', selected)
            return
        end
        -- The host reports a useful error; never choose a different codec silently.
        if not mp.get_property_native('user-data/dualtheater-diagnostic', false) then
            mp.set_property('aid', 'no')
        end
    else
        mp.set_property('aid', requested)
    end
end)
