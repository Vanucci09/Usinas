from werkzeug.security import generate_password_hash

senha = "admin123"
print(generate_password_hash(senha))
