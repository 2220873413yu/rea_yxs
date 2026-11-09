"""Regression fixtures minimized from encrypted real responses; no real credentials or network."""
import tempfile,unittest
from .bounty import BountyClient
from .gscore import GScoreClient
from .test_bounty import TaskSession
from .test_gscore import PointSession
from .test_gifts import response,nested,number
from . import protocol as p
from .rewards import item_rewards,score_rewards


class NestedPrizeSession(TaskSession):
    """Match the real itemInfo container rather than the older flat GiftItem fixture."""
    def request(self,url,body=None,headers=None,timeout=20):
        result=super().request(url,body,headers,timeout)
        if url.endswith('ReceiveGift'):
            item=p.message_string(2,'随机大礼包')+number(4,3)
            return response(number(1,1)+number(10,3)+nested(12,nested(1,item)))
        return result


class ScoreReceiptSession(PointSession):
    """Use the actual three ordinary sign receipt counters alongside a verified balance delta."""
    def request(self,url,body=None,headers=None,timeout=20):
        result=super().request(url,body,headers,timeout)
        if url.endswith('GScoreSignWithAd'):return response(number(1,4)+number(3,4)+number(4,1))
        return result


class DailyNoItemSession(TaskSession):
    """Match a confirmed fixed daily gift whose response contains no actual itemInfo at all."""
    def request(self,url,body=None,headers=None,timeout=20):
        if url.endswith('GetGamesGifts'):
            gift=(p.message_string(1,'381')+nested(4,p.message_string(1,'每日礼包'))
                +nested(5,p.message_string(2,'酒馆刷新')+number(4,1))+number(6,self.task_status)
                +number(7,1)+number(8,self.used)+number(9,1)+number(14,1))
            return response(nested(2,nested(1,number(3,1187)+nested(7,gift))))
        result=super().request(url,body,headers,timeout)
        if url.endswith('ReceiveGift'):return response(number(1,1)+number(10,1))
        return result


class RewardReceiptTests(unittest.TestCase):
    def test_nested_actual_prize_is_not_empty_zero(self):
        """A real container must yield the server's prize and quantity, never ('',0)."""
        with tempfile.TemporaryDirectory() as folder:
            client=BountyClient(NestedPrizeSession(),folder);account={'profile_id':'d'*64,'headers':{}}
            state=client.query(account);client.receive(account,'抽奖礼包',state.role_key,'4156')
            self.assertEqual(client.actual_rewards,(('随机大礼包',3),))

    def test_score_receipt_exposes_four_points(self):
        """A confirmed ordinary sign records its awarded point amount for the receipt table."""
        with tempfile.TemporaryDirectory() as folder:
            client=GScoreClient(ScoreReceiptSession(),folder)
            client.signin({'profile_id':'d'*64,'headers':{}})
            self.assertEqual(client.actual_rewards,(('G分',4),))

    def test_daily_configuration_is_labelled_not_faked_as_response(self):
        """When no prize detail was returned, preserve the fixed config with an explicit source label."""
        with tempfile.TemporaryDirectory() as folder:
            session=DailyNoItemSession();session.gift_id='381';client=BountyClient(session,folder)
            account={'profile_id':'d'*64,'headers':{}};state=client.query(account)
            client.receive(account,'每日礼包',state.role_key,'381')
            self.assertEqual(client.actual_rewards,())
            self.assertIn('酒馆刷新 ×1',client.reward_description);self.assertIn('礼包配置',client.reward_description)

    def test_missing_prizes_never_create_zero_count_rows(self):
        """Empty and malformed gift entries cannot become displayable empty-name ×0 rewards."""
        self.assertEqual(item_rewards(p.parse(nested(12,nested(1,b'')))),())
        self.assertEqual(item_rewards(p.parse(nested(12,p.message_string(2,'奖品')+number(4,0)))),())

    def test_score_amount_is_dynamic_and_validated(self):
        """Five points are read from the receipt; inconsistent or missing totals remain unknown."""
        self.assertEqual(score_rewards(p.parse(number(1,5)+number(3,5))),(('G分',5),))
        self.assertEqual(score_rewards(p.parse(number(1,4)+number(3,5))),())
        self.assertEqual(score_rewards([]),())


if __name__=='__main__':unittest.main()
