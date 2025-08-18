import os
from typing import List, Optional
from dotenv import load_dotenv
from utils.logger import get_logger

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

load_dotenv()
logger = get_logger("youtube_service")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def _get_credentials(token_path: str, client_secret_path: str) -> Credentials:
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            pass
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as token:
            token.write(creds.to_json())
    return creds

def upload_video(video_path: str,
                 title: str,
                 description: str,
                 tags: Optional[List[str]] = None,
                 category_id: Optional[str] = None,
                 privacy_status: Optional[str] = None):
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRETS", "./client_secret.json")
    token_path = os.path.join(os.path.dirname(client_secret), "youtube_token.json")
    category_id = category_id or os.getenv("YOUTUBE_DEFAULT_CATEGORY_ID", "22")
    privacy_status = privacy_status or os.getenv("YOUTUBE_DEFAULT_PRIVACY_STATUS", "public")
    default_tags = os.getenv("YOUTUBE_DEFAULT_TAGS", "")
    if tags is None and default_tags:
        tags = [t.strip() for t in default_tags.split(",") if t.strip()]

    creds = _get_credentials(token_path, client_secret)
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id,
            "tags": tags or []
        },
        "status": {
            "privacyStatus": privacy_status
        }
    }

    logger.info("Uploading video to YouTube…")
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response.get("id")
    logger.info(f"Upload complete. Video ID: {video_id}")
    return video_id
