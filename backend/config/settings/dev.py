from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env("DJANGO_DEBUG", default=True)
REFRESH_COOKIE_SECURE = False
