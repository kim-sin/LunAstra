def bucket(row):
    return 'OVER' if row.get('score',0)>1 else 'ZERO'
