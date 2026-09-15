import hashlib
import json
def key(source_bytes,schema,policy,available_at,state):
    if not isinstance(source_bytes,bytes):
        raise TypeError('source_bytes must be bytes')
    obj={'source_sha256':hashlib.sha256(source_bytes).hexdigest(),'schema':schema,
         'policy':policy,'available_at':available_at,'state':state}
    text=json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()
