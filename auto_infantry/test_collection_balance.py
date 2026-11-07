"""Verify inventory allocation, native cargo extraction and read-only forecast reconciliation."""
import json
import unittest
from unittest.mock import Mock

from collection_balance import resource_balance, balanced_candidates, same_kind_limit
from connection import Connection


def snapshot(armies=(), **changes):
    """Build a confirmed account snapshot with an intentionally scarce iron balance."""
    return dict(dict(food=50000, wood=30000, iron=10000, queue_limit=3, armies=list(armies)), **changes)


def army(army_id=1, **changes):
    """Represent an ordinary trip, without any dependency on who dispatched it."""
    return dict(dict(army_id=army_id, hero_id=303, aim=1, state=2, target_id=10), **changes)


def metrics(kind=3, count=None, maximum=40000, quantity=100000):
    """Supply the native target, resident maximum and target-specific marching load."""
    return dict(target=dict(target_id=10, kind=kind, quantity=quantity),
                heroes=[dict(hero_id=303,load=maximum)],
                collectors=[] if count is None else [dict(army_id=1,hero_id=303,count=count,maximum=maximum)])


def candidates():
    """Keep the scarce resource farthest away so a distance-only regression cannot pass."""
    return [dict(kind=k,target_id=k,x=k,y=1,distance=k*10) for k in (1,2,3)]


class BalancePolicyTests(unittest.TestCase):
    """Account balances, expected goods and diversity caps determine resource choice."""

    def test_scarcity_precedes_distance_and_ties_prefer_fewer_teams(self):
        balance=resource_balance(snapshot(),{})
        self.assertEqual([r['kind'] for r in balanced_candidates(candidates(),balance)],[3,2,1])
        balance=resource_balance(snapshot([army()],food=50000,wood=50000,iron=10000),{10:metrics()})
        self.assertEqual(balance['effective'],{1:50000,2:50000,3:50000})
        self.assertEqual(balanced_candidates(candidates(),balance)[0]['kind'],1)

    def test_marching_estimate_uses_target_load_and_stock(self):
        balance=resource_balance(snapshot([army()]),{10:metrics(maximum=50000,quantity=25000)})
        self.assertEqual(balance['incoming'][3],25000)
        self.assertEqual(balanced_candidates(candidates(),balance)[0]['kind'],2)

    def test_collecting_maximum_replaces_cargo_and_caps_at_remaining_stock(self):
        balance=resource_balance(snapshot([army(state=6,carried_iron=5000)]),
                                 {10:metrics(count=5000,maximum=40000,quantity=20000)})
        self.assertEqual(balance['incoming'][3],25000)
        self.assertEqual(balance['counts'][3],1)
        self.assertEqual(balance['unknown'],[])

    def test_returning_cargo_does_not_use_type_slot_and_delivered_army_is_not_counted_twice(self):
        returning=army(state=9,carried_iron=25000)
        balance=resource_balance(snapshot([returning]),{})
        self.assertEqual((balance['incoming'][3],balance['counts'][3]),(25000,0))
        delivered=resource_balance(snapshot([army(state=7,carried_iron=25000)],iron=35000),{})
        self.assertEqual(delivered['effective'][3],balance['effective'][3])
        self.assertEqual(delivered['incoming'][3],0)

    def test_manual_armies_share_type_cap_and_duplicate_ids_never_double_count(self):
        a,b=army(),army(2,hero_id=305)
        balance=resource_balance(snapshot([a,a,b]),{10:dict(metrics(),heroes=[dict(hero_id=h,load=1) for h in (303,305)])})
        self.assertEqual(balance['counts'][3],2)
        self.assertEqual(balance['incoming'][3],2)
        self.assertEqual([r['kind'] for r in balanced_candidates(candidates(),balance)],[2,1])
        self.assertEqual([same_kind_limit(n) for n in range(1,7)],[1,1,2,2,3,3])

    def test_nonordinary_carried_goods_count_without_querying_or_using_ordinary_slots(self):
        balance=resource_balance(snapshot([army(aim=12,state=9,carried_iron=40000)]),{})
        self.assertEqual(balance['incoming'][3],40000)
        self.assertEqual(balance['counts'][3],0)

    def test_unknown_army_blocks_allocation_and_invalid_stock_is_not_treated_as_zero(self):
        balance=resource_balance(snapshot([army()]),{})
        self.assertEqual(balance['unknown'],[1])
        self.assertEqual(balanced_candidates(candidates(),balance),[])
        with self.assertRaises(ValueError):
            resource_balance(snapshot(iron=None),{})
        with self.assertRaises(ValueError):
            resource_balance(snapshot([army(state=6)]),{10:metrics(count=500,maximum=400)})


class ForecastTransportTests(unittest.TestCase):
    """Existing trips are queried once and reconciled against the final authoritative account state."""

    def connection(self, before, after):
        """Provide only read-only operations and require the production transport orchestration."""
        c=Connection();c.collection_call=Mock(side_effect=[before,after])
        c.refresh_heroes=Mock(return_value={'heroes':[]})
        c.query_collection=Mock(return_value=metrics())
        return c

    def test_queries_each_target_once_includes_manual_trips_and_refreshes_after_reads(self):
        state=snapshot([army(),army(2,hero_id=305)])
        c=self.connection(state,state)
        result=c.collection_balance(lambda:False)
        c.query_collection.assert_called_once_with(10)
        c.refresh_heroes.assert_called_once()
        self.assertEqual(result['balance']['unknown'],[2])
        self.assertTrue(all(call.args==('collect_balance_state',) for call in c.collection_call.call_args_list))

    def test_arrival_during_reads_uses_new_inventory_without_old_income(self):
        c=self.connection(snapshot([army()]),snapshot(iron=50000))
        result=c.collection_balance(lambda:False)['balance']
        self.assertEqual(result['effective'][3],50000)
        self.assertEqual(result['incoming'][3],0)

    def test_empty_and_returning_only_accounts_need_no_forecast_server_query(self):
        state=snapshot([army(state=9,carried_iron=123)])
        c=self.connection(state,state)
        self.assertEqual(c.collection_balance(lambda:False)['balance']['incoming'][3],123)
        c.refresh_heroes.assert_not_called();c.query_collection.assert_not_called()

    def test_cancellation_prevents_the_next_target_query(self):
        state=snapshot([army(),army(2,target_id=20)])
        c=self.connection(state,state)
        cancelled=[False]
        def query(target):
            """Simulate the user stopping immediately after a single read response."""
            cancelled[0]=True;return metrics()
        c.query_collection.side_effect=query
        with self.assertRaises(InterruptedError):
            c.collection_balance(lambda:cancelled[0])
        c.query_collection.assert_called_once_with(10)
        c.refresh_heroes.assert_not_called()

    def test_expired_planning_read_refreshes_once_without_retrying_any_action(self):
        """A slow earlier region query may expire army freshness before balancing starts."""
        c=self.connection(snapshot(),snapshot())
        c.collection_call.side_effect=[RuntimeError('Fresh army state is required for resource balancing'),
                                       snapshot(),snapshot()]
        result=c.collection_balance(lambda:False)
        self.assertEqual(result['balance']['effective'][3],10000)
        c.refresh_heroes.assert_called_once();c.query_collection.assert_not_called()
        c.collection_call.side_effect=RuntimeError('Fresh army state is required for resource balancing')
        c.refresh_heroes.reset_mock()
        with self.assertRaises(RuntimeError):
            c.collection_balance(lambda:False)
        c.refresh_heroes.assert_called_once()


class NativeBalanceTests(unittest.TestCase):
    """Exercise the production Lua fields, not just Python-created snapshots."""

    def setUp(self):
        """Reuse the isolated native fixture without exposing its test class to discovery twice."""
        from test_collection_runtime import CollectionLuaTests
        fixture=CollectionLuaTests();fixture.setUp();fixture.prepare();self.lua=fixture.lua

    def test_native_stock_cargo_and_enemy_exclusion(self):
        """Only the own list contributes, and only70001/2/3 goods are resources."""
        self.lua.execute('''
         local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
         m.getMySLGResource=function() return {100,200,300} end
         local a={[1]=1,[4]=9,[5]=1,[6]=10,[15]={[1]=303},[12]=list({{70002,500},{71004,99}})}
         m._myActionState[2]=list({a,a})
         m._myActionState[3]=list({{[1]=2,[4]=6,[5]=1,[15]={[1]=305},[12]=list({{70003,9999}})}})
        ''')
        state=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_balance_state()'))
        self.assertEqual((state['food'],state['wood'],state['iron']),(100,200,300))
        self.assertEqual(len(state['armies']),1)
        self.assertEqual(state['armies'][0]['carried_wood'],500)
        self.assertEqual(state['armies'][0]['carried_iron'],0)

    def test_resident_server_maximum_is_extracted_from_matching_army(self):
        """The resource detail contains its own collector count/max independent of hero load."""
        self.lua.execute('''
         Game.mainObserver:updateSelf({id=-9995,updateData={0,
          {{{{101,59},2792},32002,nil,list({}),nil,20000},
           list({{{[1]=42,[15]={[1]=305}},1234,32100,300}})}}})
        ''')
        result=json.loads(self.lua.execute('return REA_AUTO_INFANTRY.collect_metrics()'))
        self.assertEqual(result['collectors'],[dict(army_id=42,hero_id=305,count=1234,maximum=32100)])

    def test_final_send_guard_blocks_manual_same_kind_trip_added_after_planning(self):
        """A human departure between planning and send cannot exceed the two-queue diversity cap."""
        self.lua.execute('''
         local m=CSLTypes.ModelManager.sharedInstance():getModel(CSLTypes.SLGMainModel)
         m._myActionState[2]=list({{[1]=9,[4]=2,[5]=1,[6]=20,[15]={[1]=305},[12]=list({{70003,1}})}})
        ''')
        ok,error=self.lua.execute('return pcall(REA_AUTO_INFANTRY.collect_dispatch,2792,303,3,2,1,1,20,101,191,1)')
        self.assertFalse(ok);self.assertIn('same-resource limit',error)
        self.assertEqual(len(self.lua.globals().Game.trips),0)
