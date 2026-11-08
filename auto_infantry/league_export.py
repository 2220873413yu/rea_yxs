"""Click-owned, serial export of saved alliance members; no timers, scans or credential export."""
import copy
import math
import os
import tempfile
import threading
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from collection_display import display_time
from map_index_store import scope_key

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
ROLES=('最强武将','展示武将1','展示武将2','展示武将3')


def export_cells(member,snapshot,status):
    """Keep existing hero groups intact and expose strongest-hero power as a separate sortable number."""
    user_id=(snapshot or {}).get('display_id')
    cells=[member.get('league_name',''),(snapshot or {}).get('nickname')or member['name'],
           str(user_id)if type(user_id)is int and user_id>0 else'',f"{member['x']},{member['y']}"]
    heroes={h['role']:h for h in (snapshot or {}).get('heroes',[])}
    power=heroes.get('最强武将',{}).get('power')
    cells.append(power if type(power)in(int,float)and math.isfinite(power)and power>=0 else None)
    for role in ROLES:
        hero=heroes.get(role)
        if hero is None:
            cells.extend(['未返回'if snapshot is not None else'未查询']*3);continue
        info='\n'.join([hero['name'],*[f'{label}：{hero.get(key) if hero.get(key)is not None else "未知"}'
                        for key,label in (('power','战力'),('level','等级'),('star','星级'))]])
        gems='\n'.join(f"槽{g['slot']}：{g['name']}"+(f" · {g['level']}级"if'level'in g else'')for g in sorted(hero.get('gems',[]),key=lambda g:g['slot']))
        gear='\n'.join(f"槽{e['slot']}：{e['name']}"for e in sorted(hero.get('equipment',[]),key=lambda e:e['slot']))
        cells.extend([info,gems or'未返回',gear or'未返回'])
    cells.extend([status,display_time(snapshot['confirmed_ms'])if snapshot and snapshot.get('confirmed_ms')else'—'])
    return cells


def write_export(path,scope,entries,reason):
    """Write sortable numeric power plus literal profile text, filters and frozen member columns atomically."""
    destination=Path(path)
    if destination.suffix.lower()!='.xlsx':raise ValueError('导出文件必须为 .xlsx')
    headers=['联盟','玩家昵称','用户ID','主城坐标（记录）','最强武将战力']
    for role in ROLES:headers.extend([role,role+'·宝具',role+'·装备'])
    headers+=['查询状态','确认时间（北京时间）']
    zone,map_id=scope_key(scope)
    rows=[['联盟成员武将资料'],[f'区服 {zone} / 地图 {map_id}；已记录成员 {len(entries)} 人；{reason}'],
          ['仅包含本地已记录成员，坐标为历史记录；武将资料为本次点击查询所得，不代表完整武将名单。'],headers]
    rows.extend(export_cells(e['member'],e.get('snapshot'),e['status'])for e in entries)
    ET.register_namespace('',NS)
    sheet=ET.Element('{'+NS+'}worksheet')
    def add(parent,name,**attrs):
        """Create schema-qualified worksheet elements with text-safe attributes."""
        return ET.SubElement(parent,'{'+NS+'}'+name,{k:str(v)for k,v in attrs.items()})
    add(sheet,'dimension',ref=f'A1:S{len(rows)}')
    views=add(sheet,'sheetViews');view=add(views,'sheetView',workbookViewId=0,showGridLines=0)
    add(view,'pane',xSplit=4,ySplit=4,topLeftCell='E5',activePane='bottomRight',state='frozen')
    add(view,'selection',pane='bottomRight',activeCell='E5',sqref='E5')
    add(sheet,'sheetFormatPr',defaultRowHeight=22)
    columns=add(sheet,'cols')
    for i,width in enumerate([18,20,22,20,19]+[24,33,34]*4+[42,26],1):add(columns,'col',min=i,max=i,width=width,customWidth=1)
    data=add(sheet,'sheetData')
    for row_number,values in enumerate(rows,1):
        row=add(data,'row',r=row_number,ht=125 if row_number>4 else 28,customHeight=1)
        for col,value in enumerate(values):
            style=(2+(col-5)//3 if 5<=col<17 else 1)if row_number==4 else(6 if row_number==1 else 0)
            if value is None:
                add(row,'c',r=f'{chr(65+col)}{row_number}',s=style);continue
            if type(value)in(int,float):
                cell=add(row,'c',r=f'{chr(65+col)}{row_number}',t='n',s=style)
                add(cell,'v').text=str(value);continue
            # All user-supplied names remain literal strings, including leading '=' or '+'.
            cell=add(row,'c',r=f'{chr(65+col)}{row_number}',t='inlineStr',s=style)
            text=add(add(cell,'is'),'t');text.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
            text.text=''.join(c for c in str(value)if c in '\t\n\r'or 32<=ord(c)<=0xD7FF or 0xE000<=ord(c)<=0xFFFD or 0x10000<=ord(c)<=0x10FFFF)[:32767]
    add(sheet,'autoFilter',ref=f'A4:S{len(rows)}')
    merges=add(sheet,'mergeCells',count=3)
    for number in (1,2,3):add(merges,'mergeCell',ref=f'A{number}:S{number}')
    add(sheet,'pageMargins',left=.25,right=.25,top=.5,bottom=.5,header=.2,footer=.2)
    add(sheet,'pageSetup',orientation='landscape',paperSize=9)
    fills=['23435A','285C67','40566F','575A76']
    header_styles=''.join(f'<xf fontId="1" fillId="{fill}" borderId="0" numFmtId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>'for fill in (2,2,3,4,5))
    styles=f'''<styleSheet xmlns="{NS}"><fonts count="3"><font><sz val="10"/><name val="Microsoft YaHei"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Microsoft YaHei"/></font><font><b/><sz val="14"/><name val="Microsoft YaHei"/></font></fonts><fills count="6"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>{''.join('<fill><patternFill patternType="solid"><fgColor rgb="FF'+c+'"/><bgColor indexed="64"/></patternFill></fill>'for c in fills)}</fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="7"><xf fontId="0" fillId="0" borderId="0" numFmtId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>{header_styles}<xf fontId="2" fillId="0" borderId="0" numFmtId="0" xfId="0"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    files={
      '[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
      '_rels/.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
      'xl/workbook.xml':f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="联盟成员资料" sheetId="1" r:id="rId1"/></sheets></workbook>',
      'xl/_rels/workbook.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
      'xl/styles.xml':styles,
      'xl/worksheets/sheet1.xml':ET.tostring(sheet,encoding='utf-8',xml_declaration=True)}
    fd,temp=tempfile.mkstemp(prefix='.league-export-',suffix='.xlsx',dir=destination.parent);os.close(fd)
    try:
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED)as archive:
            for name,content in files.items():archive.writestr(name,content)
        os.replace(temp,destination)
    finally:
        if os.path.exists(temp):os.unlink(temp)


class LeagueExportService:
    """Process at most one saved player per worker turn, sharing the existing manual-query gate."""

    def __init__(self,worker,writer=write_export):
        """Keep export state idle until a worker-owned explicit click provides its member snapshot."""
        self.worker=worker;self.writer=writer;self.active=False;self.cancel=threading.Event()
        self.entries=[];self.cursor=0;self.scope=None;self.path=None

    def begin(self,league_id,path):
        """Snapshot only this league's already saved records; never fetch a roster or scan new areas."""
        rows=[copy.deepcopy(r)for r in self.worker.map_index.players.values()if r['league_id']==league_id]
        if not rows:raise ValueError('该联盟没有已记录成员，请先搜索本图用户')
        scope_key(self.worker.map_index.scope)
        if Path(path).suffix.lower()!='.xlsx':raise ValueError('导出文件必须为 .xlsx')
        self.entries=[dict(member=r,snapshot=None,status='未查询')for r in sorted(rows,key=lambda r:(r['name'],r['x'],r['y']))]
        self.scope=copy.deepcopy(self.worker.map_index.scope);self.path=str(path);self.cursor=0
        self.active=True;self.progress()

    def progress(self):
        """Report finite export progress without adding any server requests."""
        self.worker.publish(league_export_progress=dict(active=self.active,done=self.cursor,total=len(self.entries),path=self.path))

    def stop(self):
        """Cancel the current wait and all unsent requests; retain obtained rows for a partial workbook."""
        self.cancel.set()

    def finish(self,reason):
        """Save confirmed rows plus explicit failures/unqueried rows, then release the shared click gate."""
        for entry in self.entries[self.cursor:]:entry['status']='未查询：'+reason
        try:
            self.writer(self.path,self.scope,self.entries,reason)
            message=f'{reason}；成功{sum(e["snapshot"]is not None for e in self.entries)}/{len(self.entries)}人；已保存：{self.path}'
        except Exception as error:message='Excel保存失败：'+str(error).splitlines()[0]
        self.active=False
        with self.worker.guard:self.worker.player_busy=False
        self.progress();self.worker.publish(player_busy=False,league_query_status=message)

    def tick(self,connection):
        """Query one exact saved identity; stop on uncertainty/manual interference instead of retrying."""
        if not self.active:return
        if self.cancel.is_set()or self.worker.closing.is_set():self.finish('导出已取消');return
        if self.cursor==len(self.entries):self.finish('导出完成');return
        entry=self.entries[self.cursor]
        try:
            if scope_key(connection.map_index_call('context'))!=scope_key(self.scope):raise RuntimeError('账号或地图已改变')
            snapshot=connection.query_map_index_player(self.scope,entry['member'],lambda:self.cancel.is_set()or self.worker.closing.is_set())
            if self.cancel.is_set()or self.worker.closing.is_set():raise InterruptedError('导出已取消')
            entry['snapshot']=snapshot
            entry['status']=('成功（本地缓存）'if snapshot.get('from_cache')else'成功')if snapshot.get('heroes')else'成功（未返回武将）'
            if snapshot.get('cache_warning'):entry['status']+='；'+snapshot['cache_warning']
        except Exception as error:
            entry['status']='查询失败：'+str(error).splitlines()[0][:220]
            self.cursor+=1
            if '服务器拒绝'not in str(error):self.finish('导出停止：'+str(error).splitlines()[0][:160]);return
        else:self.cursor+=1
        self.progress()
        if self.cursor==len(self.entries):self.finish('导出完成');
