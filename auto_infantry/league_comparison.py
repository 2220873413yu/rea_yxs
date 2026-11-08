"""Local-only comparison of reported membership totals and saved map sightings."""


def checked_league_snapshot(snapshot):
    """Persist only public totals/time from a successful explicit league-list query."""
    if snapshot is None:return None
    confirmed=snapshot.get('confirmed_ms')
    if type(confirmed)is not int or not 0<=confirmed<=9007199254740991:raise ValueError('联盟人数更新时间无效')
    leagues=[];seen=set()
    for row in snapshot['leagues']:
        league_id=row.get('league_id');count=row.get('member_count');name=row.get('name')
        if (type(league_id)is not int or not 0<league_id<=9007199254740991 or type(count)is not int or
            count<0 or not isinstance(name,str)or len(name)>512 or league_id in seen):
            raise ValueError('联盟人数统计字段无效')
        seen.add(league_id);leagues.append(dict(league_id=league_id,name=name,member_count=count))
    return dict(confirmed_ms=confirmed,leagues=leagues)


def compare_leagues(players,snapshot=None):
    """Deduplicate identities, use their latest recorded league and never treat a population gap as an error."""
    latest={}
    for player in players:
        previous=latest.get(player['record_key'])
        if previous is None or player['observed_ms']>=previous['observed_ms']:latest[player['record_key']]=player
    groups={}
    for player in latest.values():
        league_id=player['league_id']
        group=groups.setdefault(league_id,dict(league_id=league_id,name=player['league_name']or'未入盟',
            discovered=0,observed_ms=0,total=None,confirmed_ms=0))
        group['discovered']+=1;group['observed_ms']=max(group['observed_ms'],player['observed_ms'])
    if snapshot:
        for league in snapshot['leagues']:
            league_id=league['league_id']
            group=groups.setdefault(league_id,dict(league_id=league_id,discovered=0,observed_ms=0))
            group.update(name=league['name'],total=league['member_count'],confirmed_ms=snapshot['confirmed_ms'])
    result=[]
    for group in groups.values():
        total=group['total'];difference=None if total is None else total-group['discovered']
        note=('接口人数未查询'if difference is None else'人数或归属可能已变化'if difference<0 else'差额仅供参考')
        result.append({**group,'difference':difference,'note':note})
    return sorted(result,key=lambda row:(row['name'],row['league_id']))
