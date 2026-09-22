"""Local-only desktop OAuth. Not a multi-user web authentication backend."""

import os
import tempfile
import webbrowser
from pathlib import Path

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from oauthlib.oauth2 import OAuth2Error
from requests.exceptions import RequestException

from app.services.google_calendar import CalendarError

SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]
SECRET_DIR = Path(__file__).resolve().parents[2] / ".secrets" / "google-calendar"
CLIENT_FILE = SECRET_DIR / "credentials.json"
TOKEN_FILE = SECRET_DIR / "token.json"


def _save(credentials: Credentials, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            stream.write(credentials.to_json())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def get_credentials(
    *, authorize: bool = False, client_file: Path = CLIENT_FILE, token_file: Path = TOKEN_FILE
) -> Credentials:
    try:
        if authorize:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
            credentials = flow.run_local_server(
                host="127.0.0.1",
                port=0,
                timeout_seconds=180,
                authorization_prompt_message="브라우저에서 Google 읽기 권한에 동의하세요.",
                success_message="인증이 완료되었습니다. 이 창을 닫아도 됩니다.",
                prompt="consent",
                access_type="offline",
            )
            if not credentials.has_scopes(SCOPES):
                raise CalendarError("일정 읽기 권한에 동의한 후 다시 인증하세요.")
            _save(credentials, token_file)
            return credentials
        if not token_file.exists():
            raise CalendarError("저장된 인증이 없습니다. 먼저 auth 명령을 실행하세요.")
        credentials = Credentials.from_authorized_user_file(str(token_file))
        if set(credentials.scopes or []) != set(SCOPES):
            raise CalendarError("저장된 권한이 다릅니다. auth 명령으로 다시 인증하세요.")
        if not credentials.valid:
            if not credentials.refresh_token:
                raise CalendarError("갱신 토큰이 없습니다. auth 명령으로 다시 인증하세요.")
            credentials.refresh(Request())
            _save(credentials, token_file)
        return credentials
    except (
        GoogleAuthError,
        OAuth2Error,
        RequestException,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        webbrowser.Error,
    ):
        raise CalendarError(
            "Google 인증에 실패했습니다. 인증정보 파일과 네트워크를 확인하고 auth로 재인증하세요."
        ) from None
