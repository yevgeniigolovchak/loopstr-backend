from factory import Faker, Sequence, post_generation
from factory.django import DjangoModelFactory

USER_PASSWORD = "SecretPassword1"


class UserFactory(DjangoModelFactory):
    email = Sequence(lambda n: f"user{n}@example.com")
    full_name = Faker("name")

    class Meta:
        model = "users.User"
        django_get_or_create = ("email",)
        skip_postgeneration_save = True

    @post_generation
    def password(self, create, extracted, **kwargs):
        """Hash the password so tests can log in with `USER_PASSWORD`."""
        self.set_password(extracted or USER_PASSWORD)
        if create:
            self.save(update_fields=("password",))
