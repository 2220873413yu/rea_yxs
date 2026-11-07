local class=package.loaded.SLGBuildingsController
local controller=class.__instanceDict._instance
assert(type(controller)=="table", "Buildings controller is not initialized")
controller:sendTSLGGetBarrackReq()
return "Barrack refresh requested; no training or items used"
