class UserDB:
    def __init__(self):
        self._rows = {}

    def insert(self, user):
        self._rows[user["id"]] = user

    def delete(self, user_id):
        self._rows.pop(user_id, None)

    def find(self, user_id):
        return self._rows.get(user_id)

    def update_name(self, user_id, new_name):
        if user_id in self._rows:
            self._rows[user_id]["name"] = new_name


db = UserDB()


def persist_user(user):
    db.insert(user)


def remove_user(user_id):
    db.delete(user_id)


def sync_user_to_db(user):
    persist_user(user)


def lookup_user(user_id):
    return db.find(user_id)
