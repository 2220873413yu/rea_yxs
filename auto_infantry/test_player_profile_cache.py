"""Persistence, scope isolation, public-ID export reuse and transport-free cache hits."""
import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from connection import Connection
from controller import Worker
from player_profile_cache import PlayerProfileCache
from test_league_export import profile,member,SCOPE


def cipher(data,decrypt=False):
    """Make the encrypted-storage boundary visible without depending on Windows user credentials."""
    if decrypt:
        if not data.startswith(b'encrypted:'):raise ValueError('not encrypted')
        return data[10:][::-1]
    return b'encrypted:'+data[::-1]


class ProfileCacheTests(unittest.TestCase):
    """Keep stable user IDs distinct from names/positions while honoring platform and map boundaries."""

    def setUp(self):
        """Use an isolated local folder so tests cannot read or clear real player caches."""
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.cache=PlayerProfileCache(self.temp.name,cipher)

    def test_restart_reuses_public_id_and_exact_identity_without_freshening_timestamp(self):
        """Both lookup paths share the same saved payload and return independent copies."""
        identity=member(1)['identity'];snapshot=profile();snapshot['token']='must not persist'
        self.cache.put(SCOPE,snapshot,identity)
        restored=PlayerProfileCache(self.temp.name,cipher)
        by_id=restored.get(SCOPE,user_id=snapshot['display_id']);by_identity=restored.get(SCOPE,identity=identity)
        self.assertEqual(by_id,by_identity);self.assertTrue(by_id['from_cache'])
        self.assertEqual(by_id['confirmed_ms'],1000)
        by_id['heroes'].clear();self.assertEqual(len(restored.get(SCOPE,identity=identity)['heroes']),4)
        decoded=cipher(self.cache.path(SCOPE).read_bytes(),decrypt=True).decode()
        self.assertNotIn('must not persist',decoded);self.assertNotIn(identity[1],decoded)

    def test_scope_platform_and_clear_are_isolated_and_missing_ids_are_not_cached(self):
        """Clearing one map drops all its alias paths and survives restart, preserving other maps and records."""
        identity=member(1)['identity'];other={**SCOPE,'map_id':99}
        self.cache.put(SCOPE,profile(),identity);self.cache.put(other,profile(),identity)
        self.assertIsNone(self.cache.get(SCOPE,identity=[*identity[:3],1]))
        self.assertIsNone(self.cache.get({**SCOPE,'zone_id':2},user_id=profile()['display_id']))
        sighting=Path(self.temp.name)/'map-record.keep';sighting.write_text('keep')
        self.cache.clear(SCOPE)
        self.assertIsNone(self.cache.get(SCOPE,user_id=profile()['display_id']))
        self.assertIsNone(PlayerProfileCache(self.temp.name,cipher).get(SCOPE,identity=identity))
        self.assertIsNotNone(self.cache.get(other,identity=identity));self.assertTrue(sighting.exists())
        invalid=profile();invalid.pop('display_id')
        with self.assertRaises(ValueError):self.cache.put(SCOPE,invalid,identity)

    def test_corrupt_cache_can_be_explicitly_cleared_without_falling_back_to_network(self):
        """A broken local file has an actionable error and is removed only by the user's clear action."""
        self.cache.path(SCOPE).write_bytes(b'broken')
        with self.assertRaisesRegex(RuntimeError,'清空资料缓存'):self.cache.get(SCOPE,user_id=7)
        self.cache.clear(SCOPE);self.assertIsNone(self.cache.get(SCOPE,user_id=7))


class CachedConnectionTests(unittest.TestCase):
    """Exercise production connection entry points while keeping all real server transports mocked."""

    def setUp(self):
        """Install an isolated cache and local-only scope/roster lookups on a real Connection object."""
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.connection=Connection();self.connection.profile_cache=PlayerProfileCache(self.temp.name,cipher)
        self.connection.map_index_call=Mock(return_value=SCOPE.copy())
        self.connection.ensure_map_index=Mock();self.connection._install_player_adapter=Mock()
        self.connection.league_query_installed=True
        self.connection.league_query_call=Mock(return_value=member(1)['identity'])
        self.connection._query_map_index_player=Mock(return_value=profile())
        self.connection.player_call=Mock(return_value=member(1)['identity'])
        self.connection.script=Mock()

    def test_saved_member_miss_queries_once_then_export_and_id_queries_hit_after_restart(self):
        """Repeated saved-member and public-ID requests never instantiate a response log on a hit."""
        c=self.connection;row=member(1)
        first=c.query_map_index_player(SCOPE,row,lambda:False)
        c.profile_cache=PlayerProfileCache(self.temp.name,cipher)
        with patch('connection.GameResponseLog',side_effect=AssertionError('network log on cache hit')):
            second=c.query_map_index_player(SCOPE,row,lambda:False)
            by_id=c.query_player(first['display_id'],lambda:False)
            roster=c.query_league_members('member',1,lambda:False)
        c._query_map_index_player.assert_called_once()
        self.assertTrue(second['from_cache']);self.assertTrue(by_id['from_cache']);self.assertTrue(roster['from_cache'])
        self.assertEqual(c.league_query_call.call_args.args,('member_identity',1))
        c.clear_player_profile_cache();c.query_map_index_player(SCOPE,row,lambda:False)
        self.assertEqual(c._query_map_index_player.call_count,2)

    def test_scope_change_cancellation_and_failure_never_store_wrong_profiles(self):
        """A cache hit cannot bypass cancellation/map guards; failed requests never poison future queries."""
        c=self.connection;row=member(1);c.profile_cache.put(SCOPE,profile(),row['identity'])
        with self.assertRaises(InterruptedError):c.query_map_index_player(SCOPE,row,lambda:True)
        c.map_index_call.return_value={**SCOPE,'map_id':99}
        with self.assertRaises(RuntimeError):c.query_map_index_player(SCOPE,row,lambda:False)
        c.map_index_call.return_value=SCOPE;c.profile_cache.clear(SCOPE)
        c._query_map_index_player.side_effect=RuntimeError('服务器拒绝')
        with self.assertRaises(RuntimeError):c.query_map_index_player(SCOPE,row,lambda:False)
        self.assertIsNone(c.profile_cache.get(SCOPE,identity=row['identity']))

    def test_direct_public_id_miss_is_saved_and_reused(self):
        """Successful direct ID lookup populates the same persistent public-ID cache."""
        c=self.connection
        with patch('player_query.query_player',return_value=profile())as network,patch('connection.GameResponseLog'):
            c.query_player(profile()['display_id'],lambda:False)
            hit=c.query_player(profile()['display_id'],lambda:False)
            saved=c.query_map_index_player(SCOPE,member(1),lambda:False)
        network.assert_called_once();self.assertTrue(hit['from_cache'])
        self.assertTrue(saved['from_cache']);c._query_map_index_player.assert_not_called()

    def test_repeated_alliance_export_and_explicit_clear_control_real_request_counts(self):
        """Two full export passes share persistent profiles; clearing causes exactly one new query per player."""
        c=self.connection;worker=Worker(queue.Queue());worker.connection=c
        worker.map_index.scope=SCOPE.copy();worker.map_index.players={str(i):member(i)for i in (1,2)}
        worker.league_export.writer=Mock()
        def response(scope,row,cancelled):
            """Return a distinct public ID for each of the two exact saved native identities."""
            result=profile();result['display_id']+=row['identity'][0];return result
        c._query_map_index_player.side_effect=response
        for attempt in range(3):
            if attempt==2:c.clear_player_profile_cache()
            worker.request_league_export(42,'sample.xlsx');worker.player_tick(c)
            while worker.league_export.active:worker.league_export.tick(c)
            self.assertEqual(c._query_map_index_player.call_count,(2,2,4)[attempt])
            if attempt==1:
                self.assertTrue(all(e['snapshot']['from_cache']for e in worker.league_export.entries))
                self.assertTrue(all('本地缓存'in e['status']for e in worker.league_export.entries))

    def test_clear_button_worker_action_never_queries_or_erases_member_records(self):
        """Clearing is serialized with export/player actions and only invokes the dedicated local operation."""
        worker=Worker(queue.Queue());worker.connection=self.connection
        worker.map_index.players={'one':member(1)}
        worker.request_league_query('clear_profile_cache',0)
        self.connection.clear_player_profile_cache=Mock()
        worker.player_tick(self.connection)
        self.connection.clear_player_profile_cache.assert_called_once()
        self.assertEqual(len(worker.map_index.players),1);self.assertFalse(worker.player_busy)


if __name__=='__main__':unittest.main()
