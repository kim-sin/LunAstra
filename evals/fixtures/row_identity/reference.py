def join_rows(rows, outcomes):
    lookup = {}
    for row in outcomes:
        key = (row['group'], row['position'])
        if key in lookup:
            raise ValueError('duplicate outcome key')
        lookup[key] = row['outcome']
    seen = set()
    result = []
    for row in rows:
        key = (row['group'], row['position'])
        if key in seen:
            raise ValueError('duplicate row key')
        seen.add(key)
        result.append(dict(row, outcome=lookup.get(key)))
    return result
