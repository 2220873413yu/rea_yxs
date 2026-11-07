"""Read only public cached trial battle/result fields; never send a game request."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'auto_infantry'))
from connection import Connection

SOURCE=r'''
local mm=CSLTypes.ModelManager.sharedInstance()
local main=mm:getModel(CSLTypes.SLGMainModel)
local sit=main:getTSLGSitDownRsp()
local pve=mm:getModel(CSLTypes.PVEModel):getTPushPVEResult()
local out={}
local function scalar(label,r)
 if type(r)~='table'then out[#out+1]=label..'='..type(r);return end
 for i=1,22 do if type(r[i])=='number'or type(r[i])=='boolean'then out[#out+1]=label..'['..i..']='..tostring(r[i])end end
end
scalar('sit',sit);scalar('sit.info',sit and sit[11]);scalar('result',pve);scalar('result.info',pve and pve[16])
return table.concat(out,'\n')
'''

if __name__=='__main__':
    c=Connection()
    try:
        c.attach()
        print(c.script.exports_sync.query(SOURCE))
    finally:
        c.close()
