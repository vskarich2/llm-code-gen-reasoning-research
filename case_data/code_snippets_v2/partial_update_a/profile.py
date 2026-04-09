def update_profile(user, changes):

    for key, value in changes.items():
        if key == "name":
            user["name"] = value
        elif key == "email":
            user["email"] = value
        elif key == "age":
            user["age"] = value
    return user

def create_user(name, email):

    return {
        "name": name,
        "display_name": name,
        "email": email,
        "age": None,
    }
