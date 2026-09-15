def join_rows(rows, outcomes):
    lookup = {r['position']: r['outcome'] for r in outcomes}
    return [dict(r, outcome=lookup.get(r['position'], 0)) for r in rows]
