import firebase_admin
from firebase_admin import credentials, firestore
# script to test your firebase
cred = credentials.Certificate("path to your credentials")
firebase_admin.initialize_app(cred)

db = firestore.client()


def get_messages(doc_id):
    doc_ref = db.collection("conversations").document(doc_id)
    doc = doc_ref.get().to_dict()
    return doc['messages']


def add_message(doc_id, content, role):
    doc_ref = db.collection("conversations").document(doc_id)
    messages = get_messages(doc_id)
    messages.append({
        "content": content,
        "role": role
    })

    doc_ref.set({
        "messages": messages
    })


add_message("0001", "can you help me out with some errors?", "user")
add_message("0001", "Sure, could you please provide the errors.", "assistant")

