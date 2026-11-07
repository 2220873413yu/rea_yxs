"""Exercise saved-resource area loads through real Lua and transport, without a server or spending sender."""
import unittest
from unittest.mock import Mock
from pathlib import Path

from connection import Connection


COORDS=((86,94),(92,95),(97,108),(124,90),(127,68),(95,107))


class CollectionRegionTests(unittest.TestCase):
    """The game's one-slot cache is replaced on every load; independent results must survive restoration."""

    def setUp(self):
        """Use the production region observer, coordinate planner and cached-resource enumerator together."""
        from test_monster_runtime import MonsterLuaTests
        fixture=MonsterLuaTests();fixture.setUp();self.lua=fixture.lua
        self.lua.execute(Path(__file__).with_name('collection_runtime.lua').read_text(encoding='utf-8'))
        self.lua.execute('''
         local map=CSLTypes.ModelManager.sharedInstance():getModel('map')
         Game.area='99:62';Game.areaQueries={}
         Game.areaPoints={['99:62']={{86,156,4418},{92,155,4439}},
           ['100:135']={{97,142,5001},{95,143,5002}},
           ['140:165']={{124,160,5003},{127,182,5004}},['140:195']={{127,182,5004}}}
         CSLTypes.SLGMapUtils.keyToPos=function(k) return {math.floor(k/1000),k%1000,0} end
         map.mInViewDataChunkCacheManager.getAllViewData=function()
          local dict,keys={},{}
          for _,r in ipairs(Game.areaPoints[Game.area] or {}) do
           local key=r[1]*1000+r[2];keys[#keys+1]=key
           dict[key]={{ {r[1],r[2],0},r[3]},32006,nil,list({}),nil,50000}
          end
          local points={GetDictKeys=function() return list(keys) end,get_Item=function(self,key) return dict[key] end}
          return list({{mViewDataCache={ContainsKey=function(self,k) return k==1000 end,get_Item=function() return points end}}})
         end
         package.loaded.SLGMainController.__instanceDict.sendTSLGViewInfoReq=function(self,x,y,rx,ry)
          assert(rx==24 and ry==18);Game.area=x..':'..y;Game.areaQueries[#Game.areaQueries+1]=Game.area
          map:loadViewData({{x,y,0},rx,ry})
         end
        ''')
        self.c=Connection();self.c.script=Mock()
        self.c.script.exports_sync.query.side_effect=lambda source,*args:self.lua.execute(source)

    def test_missing_coordinates_group_overlap_and_survive_restore_with_collection_gate(self):
        """Two region replies find all six points, skip an already-covered third region and restore the original area."""
        result=self.c.collection_list_candidates(COORDS,9)
        self.assertEqual({(r['x'],r['y']) for r in result['rows']},set(COORDS))
        self.assertEqual(result['regions_loaded'],2)
        self.assertEqual(self.lua.globals().Game.area,'99:62')
        queries=self.lua.globals().Game.areaQueries
        self.assertEqual([queries[i] for i in range(1,len(queries)+1)],['100:135','99:62','140:165','99:62'])
        self.assertEqual(len(self.c.collection_candidates(0,0,0)),2)
        calls=self.c.script.exports_sync.query.call_args_list
        gated=[c for c in calls if 'collect_region_query(' in c.args[0]]
        self.assertEqual(len(gated),2)
        self.assertTrue(all(c.args[1:]==('collect',1,9) for c in gated))
        cleanup=[c for c in calls if 'hunt_region_query(' in c.args[0]]
        self.assertTrue(all(c.args[1] is False for c in cleanup))
        self.assertEqual(len(self.lua.globals().Game.trips),0)

    def test_all_cached_points_and_cancelled_request_do_not_load_regions(self):
        """No missing coordinate means no region request; cancellation never starts the next batch."""
        result=self.c.collection_list_candidates(COORDS[:2],9)
        self.assertEqual(result['regions_loaded'],0)
        result=self.c.collection_list_candidates(COORDS,9,lambda:True)
        self.assertEqual(result['regions_loaded'],0)
        self.assertEqual(len(self.lua.globals().Game.areaQueries),0)

    def test_cancel_after_first_response_restores_area_and_skips_remaining_regions(self):
        """Stopping a loaded lookup still cleans up the view, without starting any further discovery query."""
        cancelled=[False]
        original=self.c.script.exports_sync.query.side_effect
        def query(source,*args):
            """Simulate user cancellation after the first confirmed region's resource snapshot is copied."""
            result=original(source,*args)
            if 'collect_region_read(' in source:cancelled[0]=True
            return result
        self.c.script.exports_sync.query.side_effect=query
        result=self.c.collection_list_candidates(COORDS,9,lambda:cancelled[0])
        self.assertEqual(result['regions_loaded'],1)
        self.assertEqual(self.lua.globals().Game.area,'99:62')
        self.assertEqual(len(self.lua.globals().Game.areaQueries),2)

    def test_unknown_or_out_of_map_coordinate_is_not_deleted_or_queried_blindly(self):
        """A malformed coordinate fails before loading; a valid empty area just leaves the coordinate unresolved."""
        with self.assertRaises(Exception):self.c.collection_list_candidates(((9999,9999),),9)
        self.assertEqual(len(self.lua.globals().Game.areaQueries),0)
        result=self.c.collection_list_candidates(((200,50),),9)
        self.assertEqual(result['rows'],[])
        self.assertEqual(result['regions_loaded'],1)
        self.assertEqual(self.lua.globals().Game.area,'99:62')


if __name__=='__main__':unittest.main()
