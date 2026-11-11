"""Sign-in action rows shared by generated HTTP routes and interface policy."""

from etl_craft.core.enums import ActionName, Audit, HttpMethod
from etl_craft.services.operations import browser_sso, sessions
from etl_craft.services.operations.action_types import Action
from etl_craft.services.operations.requests import NoInput

API = "/api/v1"
GET, POST = HttpMethod.GET, HttpMethod.POST
BY_ACTION = Audit.BY_ACTION

# fmt: off
SIGN_IN_ACTIONS = (
    Action(ActionName.LOGIN_METHODS, sessions.sign_in_methods, NoInput, sessions.SignInMethods,
           None, GET, f"{API}/login/methods"),
    Action(ActionName.LOGIN, sessions.sign_in, sessions.SignIn, sessions.Session, None, POST,
           f"{API}/login/password", BY_ACTION),
    Action(ActionName.LOGIN_BROWSER_START, browser_sso.start, browser_sso.StartInput,
           browser_sso.BrowserStart, None, POST, f"{API}/login/browser/start", BY_ACTION),
    Action(ActionName.LOGIN_BROWSER_CALLBACK, browser_sso.callback, browser_sso.CallbackInput,
           browser_sso.BrowserFinish, None, POST, f"{API}/login/browser/callback", BY_ACTION),
    Action(ActionName.LOGIN_SSO, sessions.start_sso, NoInput, sessions.SsoStart, None, POST,
           f"{API}/login/sso", BY_ACTION),
    Action(ActionName.LOGIN_SSO_POLL, sessions.poll_sso, sessions.SsoPollInput, sessions.SsoPoll,
           None, POST, f"{API}/login/sso/poll", BY_ACTION),
    Action(ActionName.REFRESH, sessions.refresh, sessions.TokenInput, sessions.Session, None,
           POST, f"{API}/login/refresh"),
    Action(ActionName.LOGOUT, sessions.sign_out, sessions.SignOutInput, sessions.SignOutResult,
           None, POST, f"{API}/login/revoke", BY_ACTION),
)
# fmt: on
