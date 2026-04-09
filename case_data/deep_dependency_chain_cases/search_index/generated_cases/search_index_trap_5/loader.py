from data import DOCUMENTS

def load_documents(doc_ids):
    return [dict(DOCUMENTS[did]) for did in doc_ids]
