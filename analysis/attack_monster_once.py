"""Perform one explicitly authorized ordinary monster attack; never retry a departure."""
import json
import subprocess
import sys
import time
from pathlib import Path
import frida

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'auto_infantry'))
from connection import ADB
from game_log import GameResponseLog, tags
from game_protocol import JceReader

SEND = r'''
-- Validate the fresh target and native hero choice before consuming the one-shot marker.
function api.attack_once()
 assert(REA_ATTACK_99184_ONCE==nil,'This one-shot attack was already submitted; do not retry')
 assert(main.mTSLGLoginMapRsp==bound and main.mIsMapLoaded,'World changed')
 assert(target==152468 and detail and available and detail[1]==0 and available[1]==0,'Missing exact read responses')
 assert(detail[2]==target and detail[3]==20101 and detail[4]==0,'Monster changed or is occupied')
 local pos=CSLTypes.SLGMapUtils.logicToDisplay(detail[6])
 assert(pos[1]==99 and pos[2]==184,'Target coordinates changed')
 assert(not main:checkMaxCombateArmyCount(),'Attack queues are full')
 local enemy=main.getQuestCombatValue(tonumber(detail[5]))
 assert(enemy==30000,'Unexpected enemy power')
 local _,update=debug.getupvalue(package.loaded.SLGChooseHeroArmyInfo.__instanceDict.setCombatValue,1)
 local _,tips=debug.getupvalue(update,1)
 local best,bestPower,bestState,bestSoldier
 for i=0,available[4]:get_Count()-1 do
  local h=available[4]:get_Item(i);local id=h[1][1][3];local s=api.read_hero_state(id)
  if s.found and s.fresh and s.army_known and not s.busy and s.hero_state==0 and s.remaining_ms<=0 and
   package.loaded.SLGChooseHeroItem.__instanceDict.getActionState(h)==0 and h[2]:get_Count()>0 then
   local follower=h[2]:get_Item(0)
   if follower[2]>=2 and main.getMaxSoldierForFight(follower[1])>=2 then
    local fake={_currentSelectedHero=h,_soldierLeft={getNum=function() return 1 end},_soldierRight={getNum=function() return 1 end}}
    local power=package.loaded.SLGChooseHeroScene.__instanceDict.getMyCombatValue(fake)
    local text=CSLArrayGet(tips(power,enemy),0)
    if power>=enemy and string.find(text,'胜券在握',1,true) and (not best or power>bestPower) then
     best=h;bestPower=power;bestState=s;bestSoldier=follower[1]
    end
   end
  end
 end
 assert(best,'No idle, ready, overwhelming hero with two compatible followers')
 local heroId=best[1][1][3]
 assert(main:getMyArmyInfoByHeroGroupId(heroId)==nil,'Selected hero is assigned')
 local buildings=manager:getModel(CSLTypes.SLGBuildingsModel)
 local barrack=buildings:getTSLGGetBarrackRsp()
 assert(barrack and barrack[1]==0 and barrack[4]:get_Item(bestSoldier)[3][1]>=2,'Follower stock missing')
 local name,soldierType=debug.getupvalue(package.loaded.SLGChosenSoldier.__instanceDict.initialize,1)
 assert(name=='T_TSoldierInfo','Soldier constructor changed')
 local f=package.loaded.SLGChooseHeroLogicMonster.__instanceDict.startTrip2
 local n1,tripType=debug.getupvalue(f,1);local n2,armyType=debug.getupvalue(f,2)
 assert(n1=='T_TSLGStartArmyTripReq' and n2=='T_TMakeArmyReq','Trip constructors changed')
 assert(available[3]==3 and available[5][1]==detail[6][1] and available[5][2]==detail[6][2] and available[6]==0,'Monster target response mismatch')
 local soldiers=CSLNew(CSLTypes.CSLList)
 for _,position in ipairs({5,1}) do local s=CSLNew(soldierType);s[1]=bestSoldier;s[2]=1;s[3]=position;soldiers:Add(s) end
 local army=CSLNew(armyType);army[1]=heroId;army[2]=soldiers
 local req=CSLNew(tripType);req[1]=army;req[2]=3;req[3]=available[5];req[4]=target;req[5]=0;req[6]=nil;req[7]=0
 local receipt={hero_id=heroId,name=bestState.name,power=bestPower,enemy_power=enemy,target=target,soldier=bestSoldier,followers=2,quest=detail[5],travel_seconds=best[3]}
 _G.REA_ATTACK_99184_ONCE=receipt
 package.loaded.SLGMainController.__instanceDict.sendTSLGStartArmyTripReq(req)
 return api.encode_flat_state(receipt)
end
return 'one_shot_attack_ready'
'''


def main():
    """Freshly query, send once through a revocable gate, and save an attributed response."""
    pid = int(subprocess.check_output([ADB, '-s', 'emulator-5554', 'shell', 'pidof', 'com.qqgame.mic'],
              text=True, creationflags=subprocess.CREATE_NO_WINDOW).split()[0])
    session = frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid, realm='emulated')
    script = session.create_script((ROOT/'auto_infantry/bridge.js').read_text(encoding='utf-8'))
    script.load()
    evidence = {}
    try:
        script.exports_sync.query('assert(REA_MONSTER_READONLY==nil);REA_MONSTER_READONLY={};return "created"')
        chunks = [(ROOT/'auto_infantry/hero_runtime.lua').read_text(encoding='utf-8'),
                  (ROOT/'analysis/monster_readonly_probe.lua').read_text(encoding='utf-8').replace("return 'readonly_monster_probe_installed'", SEND)]
        for chunk in chunks:
            script.exports_sync.query('local env=setmetatable({REA_AUTO_INFANTRY=REA_MONSTER_READONLY},{__index=_G});local f=assert(loadstring('+json.dumps(chunk,ensure_ascii=False)+'));setfenv(f,env);return f()')
        log = GameResponseLog(ADB)
        script.exports_sync.query('return REA_MONSTER_READONLY.hero_refresh()')
        script.exports_sync.query('return REA_MONSTER_READONLY.monster_query(152468)')
        deadline = time.monotonic()+6
        while time.monotonic()<deadline:
            data=json.loads(script.exports_sync.query('return REA_MONSTER_READONLY.monster_result()'))
            if data['ready']:
                evidence['target_before']=data['detail']; break
            time.sleep(.2)
        else:
            raise TimeoutError('No fresh monster detail response; no attack sent')
        log.drain()
        # Reuse the bridge's departure gate only for this explicitly authorized one-shot command.
        epoch=script.exports_sync.setcollectenabled(True)
        try:
            evidence['submitted']=json.loads(script.exports_sync.query('return REA_MONSTER_READONLY.attack_once()', 'collect', 411, epoch))
            print(json.dumps(evidence['submitted'],ensure_ascii=False),flush=True)
        finally:
            script.exports_sync.setcollectenabled(False)
        sent=False
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            for record in log.drain():
                if record['tag'].startswith('s_11010_'):
                    d=tags(JceReader(record['body']).fields()); a=tags(d[0])
                    if sent or a[0]!=evidence['submitted']['hero_id'] or d[1]!=3 or d[3]!=152468:
                        raise RuntimeError('Unattributed departure; do not retry')
                    sent=True
                elif record['tag'].startswith('r_11010_') and sent:
                    d=tags(JceReader(record['body']).fields())
                    receipt={'ret':d[0]}
                    if d[0]==0:
                        a=tags(tags(d[1])[0]);identity=tags(a[15])
                        receipt.update(army_id=a[0],stage=a[4],aim=a[5],target=a[6],hero_id=identity[0])
                        assert receipt['target']==152468 and receipt['hero_id']==evidence['submitted']['hero_id']
                    evidence['response']=receipt
                    print(json.dumps(receipt,ensure_ascii=False),flush=True)
                    return
            time.sleep(.2)
        raise TimeoutError('Departure outcome uncertain; never retry')
    finally:
        (ROOT/'analysis/evidence/monster-attack-once.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        try:
            script.exports_sync.query('if REA_MONSTER_READONLY and REA_MONSTER_READONLY.monster_close then REA_MONSTER_READONLY.monster_close() end;REA_MONSTER_READONLY=nil;return "closed"')
        finally:
            script.exports_sync.close();script.unload();session.detach()


if __name__=='__main__':
    main()
