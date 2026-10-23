class LoginPage:
    def __init__(self, context):
        self.context = context

    def sign_in(self, email):
        self.context.user = email

    def reset_password(self, email):
        # dead: no step calls this. where-are-we flags unused page-object methods.
        self.context.reset_for = email
