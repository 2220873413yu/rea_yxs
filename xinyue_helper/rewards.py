"""Parse verified receipt structures without turning missing fields into empty-name zero-count prizes."""
from . import protocol as p


def item_rewards(data):
    """Read itemInfo as flat GiftItem or a tag-1 list container; never inspect candidate-pool fields."""
    out=[]
    def item(raw,depth=0):
        """Accept only a nonempty UTF-8 prize name and positive integer quantity, with bounded nesting."""
        if depth>2:return
        fields=p.parse(raw);name=p.get(fields,2);count=p.get(fields,4)
        if isinstance(name,bytes) and isinstance(count,int) and count>0:
            try:label=p.text(name)
            except p.ProtocolError:return
            if label.strip() and len(label)<=200 and all(ord(c)>=32 for c in label):
                out.append((label,count));return
        for tag,wire,value in fields:
            if tag==1 and wire==2:item(value,depth+1)
    for tag,wire,value in data:
        if tag==12 and wire==2:item(value)
    return tuple(out)


def score_rewards(data):
    """Read GScoreSignWithAdData base/ad/total fields, requiring internally consistent explicit values."""
    base=p.get(data,1);bonus=p.get(data,2,0);total=p.get(data,3)
    if all(isinstance(v,int) for v in (base,bonus,total)) and base>=0 and bonus>=0 and 0<total<=1000000 and total==base+bonus:
        return (('G分',total),)
    return ()
