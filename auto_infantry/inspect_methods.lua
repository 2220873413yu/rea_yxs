local out = {}
local names = {"SLGBuildingsController", "SLGBuildingsModel", "ProtoController", "ItemsModel", "UpgradeAccelerationNewDialog"}
for _, name in ipairs(names) do
    local class = package.loaded[name]
    for _, section in ipairs({"__declaredMethods", "__instanceDict", "static"}) do
        local keys = {}
        if class and type(class[section]) == "table" then
            for k, v in pairs(class[section]) do
                if type(k) == "string" then keys[#keys + 1] = k .. ":" .. type(v) end
            end
        end
        table.sort(keys)
        out[#out + 1] = name .. "." .. section .. "=" .. table.concat(keys, ",")
    end
end
return table.concat(out, "\n")
