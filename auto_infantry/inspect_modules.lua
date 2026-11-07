local out = {}
local names = {"SLGBuildingsController", "SLGBuildingsModel", "ProtoController", "ItemsModel", "UpgradeAccelerationNewDialog"}
for _, name in ipairs(names) do
    local value = rawget(_G, name) or (package and package.loaded and package.loaded[name])
    out[#out + 1] = name .. "=" .. type(value)
    if type(value) == "table" then
        local keys = {}
        for k, v in pairs(value) do
            if type(k) == "string" then keys[#keys + 1] = k .. ":" .. type(v) end
        end
        table.sort(keys)
        out[#out + 1] = table.concat(keys, ",")
    end
end
if package and package.loaded then
    for k,v in pairs(package.loaded) do
        if type(k) == "string" and (string.find(k, "SLGBuildings") or string.find(k, "ProtoController")) then
            out[#out + 1] = "loaded:" .. k .. ":" .. type(v)
        end
    end
end
return table.concat(out, "\n")
