def key(source_bytes, schema, policy, available_at, state):
    return str(hash((len(source_bytes),str(schema),policy)))
