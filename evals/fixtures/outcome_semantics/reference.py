import math
def bucket(row):
    if row.get('action')=='SKIP':return 'NOT_APPLICABLE'
    if row.get('status')=='cancelled':return 'CANCELLED'
    if row.get('status')!='finished':return 'UNKNOWN'
    a,b=row.get('elapsed'),row.get('budget')
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in (a,b)) or b<=0:return 'UNKNOWN'
    r=a/b
    return 'NEGATIVE' if r<0 else 'ZERO' if r==0 else 'UNDER' if r<1 else 'EXACT' if r==1 else 'OVER'
